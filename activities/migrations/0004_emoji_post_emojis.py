# Generated by Django 4.1.4 on 2022-12-14 23:49

import functools

import django.db.models.deletion
from django.db import migrations, models

import activities.models.emoji
import core.uploads
import stator.models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_identity_followers_etc"),
        ("activities", "0003_postattachment_null_thumb"),
    ]

    operations = [
        migrations.CreateModel(
            name="Emoji",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("state_ready", models.BooleanField(default=True)),
                ("state_changed", models.DateTimeField(auto_now_add=True)),
                ("state_attempted", models.DateTimeField(blank=True, null=True)),
                ("state_locked_until", models.DateTimeField(blank=True, null=True)),
                ("shortcode", models.SlugField(max_length=100)),
                ("local", models.BooleanField(default=True)),
                ("public", models.BooleanField(null=True)),
                (
                    "object_uri",
                    models.CharField(
                        blank=True, max_length=500, null=True, unique=True
                    ),
                ),
                ("mimetype", models.CharField(max_length=200)),
                (
                    "file",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=functools.partial(
                            core.uploads.upload_emoji_namer, *("emoji",), **{}
                        ),
                    ),
                ),
                ("remote_url", models.CharField(blank=True, max_length=500, null=True)),
                ("category", models.CharField(blank=True, max_length=100, null=True)),
                (
                    "state",
                    stator.models.StateField(
                        choices=[("outdated", "outdated"), ("updated", "updated")],
                        default="outdated",
                        graph=activities.models.emoji.EmojiStates,
                        max_length=100,
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated", models.DateTimeField(auto_now=True)),
                (
                    "domain",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="users.domain",
                    ),
                ),
            ],
            options={
                "unique_together": {("domain", "shortcode")},
            },
        ),
        migrations.AddField(
            model_name="post",
            name="emojis",
            field=models.ManyToManyField(
                blank=True, related_name="posts_using_emoji", to="activities.emoji"
            ),
        ),
    ]
