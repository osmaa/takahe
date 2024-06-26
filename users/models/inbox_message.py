import logging

from django.db import models
from pyld.jsonld import JsonLdError

from core.exceptions import ActivityPubError
from core.signatures import LDSignature, VerificationError, VerificationFormatError
from stator.models import State, StateField, StateGraph, StatorModel

logger = logging.getLogger(__name__)


class InboxMessageStates(StateGraph):
    received = State(try_interval=300, delete_after=86400 * 3)
    processed = State(externally_progressed=True, delete_after=86400)
    errored = State(externally_progressed=True, delete_after=86400)

    received.transitions_to(processed)
    received.transitions_to(errored)

    @classmethod
    def handle_received(cls, instance: "InboxMessage"):
        from activities.models import Post, PostInteraction, TimelineEvent
        from users.models import Block, Follow, Identity, Report
        from users.services import IdentityService

        # LD Signature verification performed out-of-band because it may
        # require fetching new actor from remote server, an action best
        # performed by the background worker rather than the HTTP server.
        try:
            instance.verify_ld_signature()
        except VerificationFormatError as e:
            logger.warning(
                "Message rejected due to bad LD signature format: %s", e.args[0]
            )
            return cls.errored
        except VerificationError as e:
            logger.info(
                "Message detected with invalid LD signature from %s %s",
                instance.message_actor(),
                e,
            )

        try:
            match instance.message_type:
                case "follow":
                    Follow.handle_request_ap(instance.message)
                case "block":
                    Block.handle_ap(instance.message)
                case "announce":
                    # Ignore Lemmy-specific likes and dislikes for perf reasons
                    # (we can't parse them anyway)
                    if instance.message_object_type in ["like", "dislike"]:
                        return cls.processed
                    PostInteraction.handle_ap(instance.message)
                case "like":
                    PostInteraction.handle_ap(instance.message)
                case "create":
                    match instance.message_object_type:
                        case "note":
                            if instance.message_object_has_content:
                                Post.handle_create_ap(instance.message)
                            else:
                                # Notes without content are Interaction candidates
                                PostInteraction.handle_ap(instance.message)
                        case "question":
                            Post.handle_create_ap(instance.message)
                        case unknown:
                            if unknown in Post.Types.names:
                                Post.handle_create_ap(instance.message)
                case "update":
                    match instance.message_object_type:
                        case "note":
                            Post.handle_update_ap(instance.message)
                        case "person":
                            Identity.handle_update_ap(instance.message)
                        case "service":
                            Identity.handle_update_ap(instance.message)
                        case "group":
                            Identity.handle_update_ap(instance.message)
                        case "organization":
                            Identity.handle_update_ap(instance.message)
                        case "application":
                            Identity.handle_update_ap(instance.message)
                        case "question":
                            Post.handle_update_ap(instance.message)
                        case unknown:
                            if unknown in Post.Types.names:
                                Post.handle_update_ap(instance.message)
                case "accept":
                    match instance.message_object_type:
                        case "follow":
                            Follow.handle_accept_ap(instance.message)
                        case None:
                            # It's a string object, but these will only be for Follows
                            Follow.handle_accept_ap(instance.message)
                        case unknown:
                            return cls.errored
                case "reject":
                    match instance.message_object_type:
                        case "follow":
                            Follow.handle_reject_ap(instance.message)
                        case None:
                            # It's a string object, but these will only be for Follows
                            Follow.handle_reject_ap(instance.message)
                        case unknown:
                            return cls.errored
                case "undo":
                    match instance.message_object_type:
                        case "follow":
                            Follow.handle_undo_ap(instance.message)
                        case "block":
                            Block.handle_undo_ap(instance.message)
                        case "like":
                            PostInteraction.handle_undo_ap(instance.message)
                        case "announce":
                            PostInteraction.handle_undo_ap(instance.message)
                        case "http://litepub.social/ns#emojireact":
                            # We're ignoring emoji reactions for now
                            pass
                        case unknown:
                            return cls.errored
                case "delete":
                    # If there is no object type, we need to see if it's a profile or a post
                    if not isinstance(instance.message["object"], dict):
                        if Identity.objects.filter(
                            actor_uri=instance.message["object"]
                        ).exists():
                            Identity.handle_delete_ap(instance.message)
                        elif Post.objects.filter(
                            object_uri=instance.message["object"]
                        ).exists():
                            Post.handle_delete_ap(instance.message)
                        else:
                            # It is presumably already deleted
                            pass
                    else:
                        match instance.message_object_type:
                            case "tombstone":
                                Post.handle_delete_ap(instance.message)
                            case "note":
                                Post.handle_delete_ap(instance.message)
                            case unknown:
                                return cls.errored
                case "add":
                    PostInteraction.handle_add_ap(instance.message)
                case "remove":
                    PostInteraction.handle_remove_ap(instance.message)
                case "move":
                    # We're ignoring moves for now
                    pass
                case "http://litepub.social/ns#emojireact":
                    # We're ignoring emoji reactions for now
                    pass
                case "flag":
                    # Received reports
                    Report.handle_ap(instance.message)
                case "__internal__":
                    match instance.message_object_type:
                        case "fetchpost":
                            Post.handle_fetch_internal(instance.message["object"])
                        case "cleartimeline":
                            TimelineEvent.handle_clear_timeline(
                                instance.message["object"]
                            )
                        case "addfollow":
                            IdentityService.handle_internal_add_follow(
                                instance.message["object"]
                            )
                        case "syncpins":
                            IdentityService.handle_internal_sync_pins(
                                instance.message["object"]
                            )
                        case unknown:
                            return cls.errored
                case unknown:
                    return cls.errored
            return cls.processed
        except (ActivityPubError, JsonLdError):
            return cls.errored


class InboxMessage(StatorModel):
    """
    an incoming inbox message that needs processing.

    Yes, this is kind of its own message queue built on the state graph system.
    It's fine. It'll scale up to a decent point.
    """

    message = models.JSONField()

    state = StateField(InboxMessageStates)

    @classmethod
    def create_internal(cls, payload):
        """
        Creates an internal action message
        """
        cls.objects.create(
            message={
                "type": "__internal__",
                "object": payload,
            }
        )

    @property
    def message_type(self):
        return self.message["type"].lower()

    @property
    def message_object_type(self) -> str | None:
        if isinstance(self.message["object"], dict):
            return self.message["object"]["type"].lower()
        else:
            return None

    @property
    def message_type_full(self):
        if isinstance(self.message.get("object"), dict):
            return f"{self.message_type}.{self.message_object_type}"
        else:
            return f"{self.message_type}"

    @property
    def message_actor(self):
        return self.message.get("actor")

    @property
    def message_object_has_content(self):
        object = self.message.get("object", {})
        return "content" in object or "contentMap" in object

    def verify_ld_signature(self):
        # Mastodon advices not implementing LD Signatures, but
        # they're widely deployed today. Validate it if one exists.
        # https://docs.joinmastodon.org/spec/security/#ld
        from urllib.parse import urldefrag

        from users.models import Identity

        document = self.message
        if "signature" not in document:
            return

        try:
            creator = urldefrag(document["signature"]["creator"]).url
            creator_identity = Identity.by_actor_uri(
                creator, create=True, transient=True
            )
            if creator_identity.public_key is None:
                creator_identity.fetch_actor()

            if creator_identity.public_key is None:
                raise VerificationError(
                    "Inbox: Could not fetch actor to verify message signature: %s",
                    creator,
                )

            LDSignature.verify_signature(document, creator_identity.public_key)
            logger.debug(
                "Inbox: %s from %s has good LD signature",
                document["type"],
                creator,
            )
            return creator_identity
        except VerificationError:
            # An invalid LD Signature might also indicate nothing but
            # a syntactical difference between implementations, so we strip
            # it out and pretend one didn't exist
            document.pop("signature")
            raise
