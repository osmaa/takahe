from django import forms
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.generic import FormView, ListView

from activities.models import Emoji
from users.decorators import moderator_required
from users.views.admin.generic import HTMXActionView


@method_decorator(moderator_required, name="dispatch")
class EmojiRoot(ListView):
    template_name = "admin/emoji.html"
    paginate_by = 50

    def get(self, request, *args, **kwargs):
        self.query = request.GET.get("query")
        self.local_only = request.GET.get("local_only")
        self.extra_context = {
            "section": "emoji",
            "query": self.query or "",
            "local_only": self.local_only,
        }
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Emoji.objects.filter().order_by("shortcode", "domain_id")
        if self.local_only:
            queryset = queryset.filter(local=True)
        if self.query:
            query = self.query.lower().strip().lstrip("@")
            queryset = queryset.filter(
                models.Q(shortcode__icontains=query) | models.Q(domain_id=query)
            )
        return queryset


@method_decorator(moderator_required, name="dispatch")
class EmojiCreate(FormView):
    template_name = "admin/emoji_create.html"
    extra_context = {"section": "emoji"}

    class form_class(forms.Form):
        shortcode = forms.SlugField(
            help_text="What users type to use the emoji :likethis:\nShould only contain 0-9, a-z and underscores",
            validators=[
                RegexValidator(r"^[a-z0-9_]+$", message="Invalid emoji shortcode")
            ],
        )
        image = forms.ImageField(
            help_text=f"The emoji image\nShould be at least 40 x 40 pixels, and under {settings.SETUP.EMOJI_MAX_IMAGE_FILESIZE_KB}KB",
        )

        def clean_image(self):
            data = self.cleaned_data["image"]
            if data.size > settings.SETUP.EMOJI_MAX_IMAGE_FILESIZE_KB * 1024:
                raise forms.ValidationError(
                    f"Image filesize is too large (actual: {data.size // 1024}KB)"
                )
            if data.image.width < 40 or data.image.height < 40:
                raise forms.ValidationError(
                    f"Image should at least 40 x 40 pixels (actual: {data.image.width} x {data.image.height} pixels)"
                )
            return data

    def form_valid(self, form):
        Emoji.objects.create(
            shortcode=form.cleaned_data["shortcode"],
            file=form.cleaned_data["image"],
            mimetype=form.cleaned_data["image"].image.get_format_mimetype(),
            local=True,
            public=True,
        )
        return redirect(Emoji.urls.admin)


@method_decorator(moderator_required, name="dispatch")
class EmojiDelete(HTMXActionView):
    """
    Deletes an emoji
    """

    model = Emoji

    def action(self, emoji: Emoji):
        emoji.delete()


@method_decorator(moderator_required, name="dispatch")
class EmojiEnable(HTMXActionView):
    """
    Sets an emoji to be enabled (or not!)
    """

    model = Emoji
    enable = True

    def action(self, emoji: Emoji):
        emoji.public = self.enable
        emoji.save()


@method_decorator(moderator_required, name="dispatch")
class EmojiCopyLocal(HTMXActionView):
    """
    Duplicates a domain emoji to be local, as long as it is usable and the
    shortcode is available.
    """

    model = Emoji

    def action(self, emoji: Emoji):
        # Force reload locals cache to avoid potential for shortcode dupes
        Emoji.locals = Emoji.load_locals()
        emoji.copy_to_local()
