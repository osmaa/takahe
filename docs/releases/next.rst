

Upgrade Notes
-------------

VAPID keys and Push notifications
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Takahē now supports push notifications if you supply a valid VAPID keypair as
the ``TAKAHE_VAPID_PUBLIC_KEY`` and ``TAKAHE_VAPID_PRIVATE_KEY`` environment
variables. You can generate a keypair via `https://web-push-codelab.glitch.me/`_.

Note that users of apps may need to sign out and in again to their accounts for
the app to notice that it can now do push notifications. Some apps, like Elk,
may cache the fact your server didn't support it for a while.
