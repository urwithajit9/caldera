import base64
from collections import namedtuple

from aiohttp import web
from aiohttp.web_exceptions import HTTPUnauthorized, HTTPForbidden
from aiohttp_security import SessionIdentityPolicy, check_permission, remember, forget
from aiohttp_security import setup as setup_security
from aiohttp_security.abc import AbstractAuthorizationPolicy
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from cryptography import fernet


class AuthService:

    User = namedtuple('User', ['username', 'password', 'permissions'])

    def __init__(self, utility_svc):
        self.log = utility_svc.create_logger('auth_svc')
        self.user_map = dict()

    async def apply(self, app, users):
        for k, v in users.items():
            self.user_map[k] = self.User(k, v, ('admin', 'user'),)
        app.user_map = self.user_map
        fernet_key = fernet.Fernet.generate_key()
        secret_key = base64.urlsafe_b64decode(fernet_key)
        storage = EncryptedCookieStorage(secret_key, cookie_name='API_SESSION')
        setup_session(app, storage)
        policy = SessionIdentityPolicy()
        setup_security(app, policy, DictionaryAuthorizationPolicy(self.user_map))

    @staticmethod
    async def logout_user(request):
        await forget(request, web.Response())
        raise web.HTTPFound('/login')

    async def login_user(self, request):
        data = await request.post()
        response = web.HTTPFound('/')
        verified = await self._check_credentials(
            request.app.user_map, data.get('username'), data.get('password'))
        if verified:
            await remember(request, response, data.get('username'))
            return response
        raise web.HTTPFound('/login')

    @staticmethod
    async def check_permissions(request):
        try:
            await check_permission(request, 'admin')
        except HTTPUnauthorized:
            raise web.HTTPFound('/login')
        except HTTPForbidden:
            raise web.HTTPFound('/login')

    async def _check_credentials(self, user_map, username, password):
        self.log.debug('%s logging in' % username)
        user = user_map.get(username)
        if not user:
            return False
        return user.password == password


class DictionaryAuthorizationPolicy(AbstractAuthorizationPolicy):

    def __init__(self, user_map):
        super().__init__()
        self.user_map = user_map

    async def authorized_userid(self, identity):
        """Retrieve authorized user id.
        Return the user_id of the user identified by the identity
        or 'None' if no user exists related to the identity.
        """
        if identity in self.user_map:
            return identity

    async def permits(self, identity, permission, context=None):
        """Check user permissions.
        Return True if the identity is allowed the permission in the
        current context, else return False.
        """
        user = self.user_map.get(identity)
        if not user:
            return False
        return permission in user.permissions


