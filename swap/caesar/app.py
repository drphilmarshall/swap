
# Collection of infrastructures to run SWAP in an online state
# with Caesar

from swap.caesar.control import ThreadedControl
from swap.utils import Singleton
import swap.config as config

from panoptes_client.panoptes import Panoptes

from getpass import getpass
import logging
from flask import Flask, request, jsonify, Response
from functools import wraps
import requests
import threading


logger = logging.getLogger(__name__)


# Actions we might take to notify caesar

# retire subject

# post score changes

# change subject workflow


# API so Caesar can notify us

# receive classification
"""
    Data required in extraction:
    unique user identifier (whether that's user_name or user_id)
    subject identifier (subject_id, object_id)
    annotation
    gold label
        Should we rely on Caesar to maintain gold labels for us?
        Do we need to push new gold labels to Caesor if so?
        Might be better to maintain them in our local db

    Should store the incoming classificadtion in our db
        Do we need validation checks to ensure we don't have
        duplicate classificationsin our db
    Should then recalculate scores

    Do we then need to respond with the updated for that subject?
        Would it be better to just send our own asynchronous
        retirement message when we see fit?
"""


"""
TODO:
    Write online controller
        Listen as reducer and process incoming classifications
        Pre-process classifications already in database
    Write request/response schema
    Write new database methods
        To store incoming classifications in cl database
"""

"""
To configure caesar:
    swap must be registered as an external extractor in caesar's config
    swap must be registered as an external reducer in caesar's config
        with no URL
"""


def needs_auth(func):
    """
    Wrapper to force authentication in HTTP request
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        auth = request.authorization
        if not auth or not self._auth.check_auth(auth.username, auth.password):
            return self._auth.authenticate()
        return func(self, *args, **kwargs)
    return wrapper


class API:

    def __init__(self, control_thread):
        self.app = Flask(__name__)
        self.control = control_thread

        user = config.online_swap._auth_username
        token = config.online_swap._auth_key
        self._auth = Auth(user, token)

    def run(self):
        self._route('/', 'scores', self.scores, ['GET'])
        self._route('/classify', 'classify', self.classify, ['POST'])
        self.app.run()

    def _route(self, route, name, func, methods=('GET')):
        self.app.add_url_rule(
            route, name, func, methods=methods)

    def get(self, subject):
        """
        Return current score of a subject
        """
        pass

    @needs_auth
    def classify(self):
        """
        Receive a classification from caesar and process it
        """
        logger.info('received classification')
        logger.debug(str(request))

        # Parse json from request
        data = request.get_json()

        logger.debug('received data %s', str(data))
        logger.debug('sending classification to swap thread')
        self.control.queue('classify', data, respond)

        # return empty response

        resp = jsonify({'status': 'ok'})
        resp.status_code = 200
        return resp

    @needs_auth
    def scores(self):
        """
        Return current score export
        """
        scores = self.control.scores()

        return jsonify(scores.full_dict())


class Address:
    config = config.online_swap

    @classmethod
    def root(cls):
        host = cls.config.caesar.host
        port = cls.config.caesar.port
        workflow = cls.config.workflow
        return cls.config.address._base % \
            {'host': host, 'port': port, 'workflow': workflow}

    @classmethod
    def reducer(cls):
        reducer = cls.config.caesar.reducer
        addr = cls.config.address._reducer
        return cls.root() + addr % {'reducer': reducer}

    @classmethod
    def swap_classify(cls):
        addr = cls.config.address._swap
        host = cls.config.host
        port = cls.config.ext_port

        username = cls.config._auth_username
        password = cls.config._auth_key
        password = Auth._mod_token(password)

        return addr % \
            {'user': username, 'pass': password,
             'host': host, 'port': port}

    @classmethod
    def config_caesar(cls):
        name = cls.config.caesar.reducer
        addr = cls.swap_classify()
        data = {'workflow': {
            'extractors_config': {name: {'type': 'external', 'url': addr}},
            'reducers_config': {name: {'type': 'external'}},
            'rules_config': []
        }}
        logger.info('compiled caesar config: %s', data)
        return data

# def generate_address():
#     """
#     Generate Caesar address to PUT reduction
#     """
#     s = config.online_swap._addr_format
#     c = config.online_swap
#
#     kwargs = {
#         'host': c.caesar.host,
#         'port': c.caesar.port,
#         'workflow': c.workflow,
#         'reducer': c.caesar.reducer
#     }
#
#     return s % kwargs


def register_swap():
    """
    Register swap as an extractor/reducer on caesar
    """
    data = Address.config_caesar()
    address = Address.root()

    logger.info('PUT to %s with %s', address, str(data))
    auth_header = AuthCaesar().auth()
    requests.put(address, headers=auth_header, json=data)
    logger.info('done')


def respond(subject):
    """
    PUT subject score to Caesar
    """
    c = config.online_swap

    address = Address.reducer()

    # address = 'http://localhost:3000'
    body = {
        'reduction': {
            'subject_id': subject.id,
            'data': {
                c.caesar.field: subject.score
            }
        }
    }

    print('responding!')
    logger.info('PUT subject %d score %.4f to caesar',
                subject.id, subject.score)

    auth_header = AuthCaesar().auth()
    requests.put(address, headers=auth_header, json=body)
    logger.debug('done')


def init_threader(swap=None):
    thread = ThreadedControl(swap=swap)
    thread.start()

    return thread


class Auth:

    def __init__(self, username, token):
        self._username = username
        self._token = self._mod_token(token)

    @staticmethod
    def _mod_token(token):
        return token.replace(' ', '').replace('\n', '')

    def check_auth(self, username, token):
        return username == self._username and token == self._token

    @staticmethod
    def authenticate():
        """
        Sends a 401 response that enables basic auth
        """
        return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})


class _AuthCaesar:

    def __init__(self):
        self.client = Panoptes(endpoint='https://panoptes-staging.zooniverse.org')
        self.lock = threading.Lock()

    @property
    def token(self):
        return self.client.get_bearer_token()

    def login(self):
        with self.lock:
            logger.info('Logging in to panoptes')
            user = input('Username: ')
            password = getpass()

            self.client.login(user, password)
            token = self.client.get_bearer_token()

        print(token)
        return token

    def auth(self, headers=None):
        logger.info('adding authorization header')
        with self.lock:
            if self.token is None:
                raise self.NotLoggedIn
            token = self.token

        if headers is None:
            headers = {}

        headers.update({
            'Authorization': 'Bearer %s' % token
        })

    class NotLoggedIn(Exception):
        def __init__(self):
            super().__init__(
                'Need to log in first. Either set panoptes oauth2 bearer '
                'token in config.online_swap.caesar.OAUTH, or try running '
                'app again with --login flag')


class AuthCaesar(_AuthCaesar, metaclass=Singleton):
    pass


# def run():
#     c = config.caesar.swap
#     app.run(host=c.bind, port=c.port, debug=c.debug)


if __name__ == '__main__':
    control = init_threader()
    api = API(control)
    api.run()