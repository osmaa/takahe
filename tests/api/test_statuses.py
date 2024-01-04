import pytest

from activities.models import Post, PostAttachment, PostAttachmentStates


@pytest.mark.django_db
def test_post_status(api_client, identity):
    """
    Tests posting, editing and deleting a status
    """
    # Create media attachment
    attachment = PostAttachment.objects.create(
        mimetype="image/webp",
        name=None,
        state=PostAttachmentStates.fetched,
        author=identity,
    )
    # Post new one
    response = api_client.post(
        "/api/v1/statuses",
        content_type="application/json",
        data={
            "status": "Hello, world!",
            "visibility": "unlisted",
            "media_ids": [attachment.id],
        },
    ).json()
    assert response["content"] == "<p>Hello, world!</p>"
    assert response["visibility"] == "unlisted"
    assert response["media_attachments"][0]["description"] is None
    status_id = response["id"]
    # Retrieve "source" version an edit would use
    response = api_client.get(f"/api/v1/statuses/{status_id}/source").json()
    assert response["text"] == "Hello, world!"
    # Post an edit
    response = api_client.put(
        f"/api/v1/statuses/{status_id}",
        content_type="application/json",
        data={
            "status": "Hello, world! Again!",
            "media_ids": [attachment.id],
            "media_attributes": [
                {"id": attachment.id, "description": "the alt text"},
            ],
        },
    ).json()
    # Check it stuck
    response = api_client.get(f"/api/v1/statuses/{status_id}").json()
    assert response["content"] == "<p>Hello, world! Again!</p>"
    assert response["media_attachments"][0]["description"] == "the alt text"
    # Delete it
    response = api_client.delete(f"/api/v1/statuses/{status_id}")
    assert response.status_code == 200
    # Check it's gone
    response = api_client.get(f"/api/v1/statuses/{status_id}")
    assert response.status_code == 404


@pytest.mark.django_db
def test_post_statusless(api_client, identity):
    """
    Tests we can post with media but no status
    """
    # Create media attachment
    attachment = PostAttachment.objects.create(
        mimetype="image/webp",
        name=None,
        state=PostAttachmentStates.fetched,
        author=identity,
    )
    # Post new one
    response = api_client.post(
        "/api/v1/statuses",
        content_type="application/json",
        data={
            "media_ids": [attachment.id],
        },
    )
    assert 200 <= response.status_code < 300
    body = response.json()
    assert body["content"] == "<p></p>"
    assert body["media_attachments"][0]["description"] is None


@pytest.mark.django_db
def test_mention_format(api_client, identity, remote_identity):
    """
    Ensures mentions work, and only have one link around them.
    """
    # Make a local post and check it
    response = api_client.post(
        "/api/v1/statuses",
        data={
            "status": "Hello, @test!",
            "visibility": "unlisted",
        },
    ).json()
    assert (
        response["content"]
        == '<p>Hello, <span class="h-card"><a href="https://example.com/@test/" class="u-url mention" rel="nofollow noopener noreferrer" target="_blank">@<span>test</span></a></span>!</p>'
    )
    assert response["visibility"] == "unlisted"

    # Make a remote post and check it
    post = Post.objects.create(
        local=False,
        author=remote_identity,
        content='<p>Hey <a href="https://example.com/@test/" class="u-url mention" rel="nofollow">@test</a></p>',
        object_uri="https://remote.test/status/12345",
    )
    post.mentions.add(identity)
    response = api_client.get(
        f"/api/v1/statuses/{post.id}",
    ).json()
    assert (
        response["text"]
        == '<p>Hey <span class="h-card"><a href="https://example.com/@test/" class="u-url mention" rel="nofollow noopener noreferrer" target="_blank">@<span>test</span></a></span></p>'
    )


@pytest.mark.django_db
def test_post_question_status(api_client):
    response = api_client.post(
        "/api/v1/statuses",
        content_type="application/json",
        data={
            "status": "Hello, world!",
            "poll": {
                "options": ["Option 1", "Option 2"],
                "expires_in": 300,
            },
        },
    ).json()

    assert response["poll"]["id"] == response["id"]
    assert response["poll"]["options"] == [
        {"title": "Option 1", "votes_count": 0},
        {"title": "Option 2", "votes_count": 0},
    ]
    assert not response["poll"]["expired"]
    assert not response["poll"]["multiple"]


@pytest.mark.django_db
def test_question_format(api_client, remote_identity):
    """
    Ensures incoming questions are property parsed.
    """
    # Make a remote question post and check it
    post = Post.objects.create(
        local=False,
        author=remote_identity,
        content="<p>Test Question</p>",
        object_uri="https://remote.test/status/123456",
        type=Post.Types.question,
        type_data={
            "type": "Question",
            "mode": "oneOf",
            "options": [
                {"name": "Option 1", "type": "Note", "votes": 10},
                {"name": "Option 2", "type": "Note", "votes": 20},
            ],
            "voter_count": 30,
            "end_time": "2022-01-01T23:04:45+00:00",
        },
    )
    response = api_client.get(f"/api/v1/statuses/{post.id}").json()
    assert response["text"] == "<p>Test Question</p>"
    assert response["poll"] == {
        "id": str(post.id),
        "expires_at": "2022-01-01T23:04:45.000Z",
        "expired": True,
        "multiple": False,
        "votes_count": 30,
        "voters_count": 30,
        "voted": False,
        "own_votes": [],
        "options": [
            {"title": "Option 1", "votes_count": 10},
            {"title": "Option 2", "votes_count": 20},
        ],
        "emojis": [],
    }


@pytest.mark.django_db
def test_content_link(api_client, identity, remote_identity):
    """
    Ensures mentions work, and only have one link around them.
    """
    # Make a local post and check it
    response = api_client.post(
        "/api/v1/statuses",
        data={
            "status": "Takahē - return to the wild - https://www.youtube.com/watch?v=IG423K3pmQI",
        },
    ).json()

    assert (
        response["content"]
        == '<p>Takahē - return to the wild - <a href="https://www.youtube.com/watch?v=IG423K3pmQI" rel="nofollow" class="ellipsis" title="www.youtube.com/watch?v=IG423K3pmQI"><span class="invisible">https://</span><span class="ellipsis">www.youtube.com/watch?v=IG423K</span><span class="invisible">3pmQI</span></a></p>'
    )
