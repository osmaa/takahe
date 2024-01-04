from datetime import timedelta
from typing import Literal

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from hatchway import ApiError, ApiResponse, Schema, api_view

from activities.models import (
    Post,
    PostAttachment,
    PostInteraction,
    PostInteractionStates,
    TimelineEvent,
)
from activities.services import PostService
from api import schemas
from api.decorators import scope_required
from api.pagination import MastodonPaginator, PaginatingApiResponse, PaginationResult
from core.models import Config


class PostPollSchema(Schema):
    options: list[str]
    expires_in: int
    multiple: bool = False
    hide_totals: bool = False

    def dict(self):
        return {
            "type": "Question",
            "mode": "anyOf" if self.multiple else "oneOf",
            "options": [
                {"name": name, "type": "Note", "votes": 0} for name in self.options
            ],
            "voter_count": 0,
            "end_time": timezone.now() + timedelta(seconds=self.expires_in),
        }


class PostStatusSchema(Schema):
    status: str | None
    in_reply_to_id: str | None = None
    sensitive: bool = False
    spoiler_text: str | None = None
    visibility: Literal["public", "unlisted", "private", "direct"] = "public"
    language: str | None = None
    scheduled_at: str | None = None
    media_ids: list[str] = []
    poll: PostPollSchema | None = None


class MediaAttributesSchema(Schema):
    id: str
    description: str


class EditStatusSchema(Schema):
    status: str
    sensitive: bool = False
    spoiler_text: str | None = None
    language: str | None = None
    media_ids: list[str] = []
    media_attributes: list[MediaAttributesSchema] = []


def post_for_id(request: HttpRequest, id: str) -> Post:
    """
    Common logic to get a Post object for an ID, taking visibility into
    account.
    """
    if request.identity:
        queryset = Post.objects.not_hidden().visible_to(
            request.identity, include_replies=True
        )
    else:
        queryset = Post.objects.not_hidden().unlisted()
    return get_object_or_404(queryset, pk=id)


@scope_required("write:statuses")
@api_view.post
def post_status(request, details: PostStatusSchema) -> schemas.Status:
    # Check text length
    if details.status and len(details.status) > Config.system.post_length:
        raise ApiError(400, "Status is too long")
    if not details.status and not details.media_ids:
        raise ApiError(400, "Status is empty")
    # Grab attachments
    attachments = [get_object_or_404(PostAttachment, pk=id) for id in details.media_ids]
    # Create the Post
    visibility_map = {
        "public": Post.Visibilities.public,
        "unlisted": Post.Visibilities.unlisted,
        "private": Post.Visibilities.followers,
        "direct": Post.Visibilities.mentioned,
    }
    reply_post = None
    if details.in_reply_to_id:
        try:
            reply_post = Post.objects.get(pk=details.in_reply_to_id)
        except Post.DoesNotExist:
            pass
    post = Post.create_local(
        author=request.identity,
        content=details.status or "",
        summary=details.spoiler_text,
        sensitive=details.sensitive,
        visibility=visibility_map[details.visibility],
        reply_to=reply_post,
        attachments=attachments,
        question=details.poll.dict() if details.poll else None,
    )
    # Add their own timeline event for immediate visibility
    TimelineEvent.add_post(request.identity, post)
    return schemas.Status.from_post(post, identity=request.identity)


@scope_required("read:statuses")
@api_view.get
def status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, interactions=interactions, identity=request.identity
    )


@scope_required("write:statuses")
@api_view.put
def edit_status(request, id: str, details: EditStatusSchema) -> schemas.Status:
    post = post_for_id(request, id)
    if post.author != request.identity:
        raise ApiError(401, "Not the author of this status")
    # Grab attachments
    attachments = [get_object_or_404(PostAttachment, pk=id) for id in details.media_ids]
    # Update all details, as the client must provide them all
    post.edit_local(
        content=details.status,
        summary=details.spoiler_text,
        sensitive=details.sensitive,
        attachments=attachments,
        attachment_attributes=details.media_attributes,
    )
    return schemas.Status.from_post(post)


@scope_required("write:statuses")
@api_view.delete
def delete_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    if post.author != request.identity:
        raise ApiError(401, "Not the author of this status")
    PostService(post).delete()
    return schemas.Status.from_post(post, identity=request.identity)


@scope_required("read:statuses")
@api_view.get
def status_source(request, id: str) -> schemas.StatusSource:
    post = post_for_id(request, id)
    return schemas.StatusSource.from_post(post)


@scope_required("read:statuses")
@api_view.get
def status_context(request, id: str) -> schemas.Context:
    post = post_for_id(request, id)
    service = PostService(post)
    ancestors, descendants = service.context(request.identity)
    interactions = PostInteraction.get_post_interactions(
        ancestors + descendants, request.identity
    )
    return schemas.Context(
        ancestors=[
            schemas.Status.from_post(
                p, interactions=interactions, identity=request.identity
            )
            for p in reversed(ancestors)
        ],
        descendants=[
            schemas.Status.from_post(
                p, interactions=interactions, identity=request.identity
            )
            for p in descendants
        ],
    )


@scope_required("write:favourites")
@api_view.post
def favourite_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    service = PostService(post)
    service.like_as(request.identity)
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, interactions=interactions, identity=request.identity
    )


@scope_required("write:favourites")
@api_view.post
def unfavourite_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    service = PostService(post)
    service.unlike_as(request.identity)
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, interactions=interactions, identity=request.identity
    )


@api_view.get
def favourited_by(
    request: HttpRequest,
    id: str,
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = 20,
) -> ApiResponse[list[schemas.Account]]:
    """
    View who favourited a given status.
    """
    post = post_for_id(request, id)

    paginator = MastodonPaginator()
    pager: PaginationResult[PostInteraction] = paginator.paginate(
        post.interactions.filter(
            type=PostInteraction.Types.like,
            state__in=PostInteractionStates.group_active(),
        ).select_related("identity"),
        min_id=min_id,
        max_id=max_id,
        since_id=since_id,
        limit=limit,
    )

    return PaginatingApiResponse(
        [
            schemas.Account.from_identity(
                interaction.identity,
                include_counts=False,
            )
            for interaction in pager.results
        ],
        request=request,
        include_params=[
            "limit",
            "id",
        ],
    )


@api_view.get
def reblogged_by(
    request: HttpRequest,
    id: str,
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = 20,
) -> ApiResponse[list[schemas.Account]]:
    """
    View who reblogged a given status.
    """
    post = post_for_id(request, id)

    paginator = MastodonPaginator()
    pager: PaginationResult[PostInteraction] = paginator.paginate(
        post.interactions.filter(
            type=PostInteraction.Types.boost,
            state__in=PostInteractionStates.group_active(),
        ).select_related("identity"),
        min_id=min_id,
        max_id=max_id,
        since_id=since_id,
        limit=limit,
    )

    return PaginatingApiResponse(
        [
            schemas.Account.from_identity(
                interaction.identity,
                include_counts=False,
            )
            for interaction in pager.results
        ],
        request=request,
        include_params=[
            "limit",
            "id",
        ],
    )


@scope_required("write:favourites")
@api_view.post
def reblog_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    service = PostService(post)
    service.boost_as(request.identity)
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, interactions=interactions, identity=request.identity
    )


@scope_required("write:favourites")
@api_view.post
def unreblog_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    service = PostService(post)
    service.unboost_as(request.identity)
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, interactions=interactions, identity=request.identity
    )


@scope_required("write:bookmarks")
@api_view.post
def bookmark_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    request.identity.bookmarks.get_or_create(post=post)
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, interactions=interactions, bookmarks={post.pk}, identity=request.identity
    )


@scope_required("write:bookmarks")
@api_view.post
def unbookmark_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    request.identity.bookmarks.filter(post=post).delete()
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, interactions=interactions, identity=request.identity
    )


@scope_required("write:accounts")
@api_view.post
def pin_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    try:
        PostService(post).pin_as(request.identity)
        interactions = PostInteraction.get_post_interactions([post], request.identity)
        return schemas.Status.from_post(
            post, identity=request.identity, interactions=interactions
        )
    except ValueError as e:
        raise ApiError(422, str(e))


@scope_required("write:accounts")
@api_view.post
def unpin_status(request, id: str) -> schemas.Status:
    post = post_for_id(request, id)
    PostService(post).unpin_as(request.identity)
    interactions = PostInteraction.get_post_interactions([post], request.identity)
    return schemas.Status.from_post(
        post, identity=request.identity, interactions=interactions
    )
