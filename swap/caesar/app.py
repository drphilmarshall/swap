
# Collection of infrastructures to run SWAP in an online state
# with Caesar

from swap.caesar.control import ThreadedControl
from swap.caesar.auth import Auth
from swap.caesar.utils.requests import Requests
import swap.config as config

import logging
from flask import Flask, request, jsonify, Response
from functools import wraps


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
        # Check if request has authorized credentials
        if not auth or not Auth().check_auth(auth.username, auth.password):
            # Send a 401 response to request auth credentials
            return Auth().authenticate()
        return func(self, *args, **kwargs)
    return wrapper


class API:
    """
    Main API endpoint for online SWAP. Manages all incoming traffic
    and routes.
    """

    def __init__(self, control_thread):
        self.app = Flask(__name__)
        self.control = control_thread

        self._recent_cl = []

    def run(self):
        # Register routes with their appropriate functions
        self._route('/', 'status', self.status, ['GET'])
        self._route('/scores', 'scores', self.scores, ['GET'])
        self._route('/classify', 'classify', self.classify, ['POST'])
        self.app.run(port=config.online_swap.port)

    def _route(self, route, name, func, methods=('GET')):
        self.app.add_url_rule(
            route, name, func, methods=methods)

    @staticmethod
    def status():
        return Response(config.online_swap.flask_responder.build_responder(config).status_string(), 200)

    def _check_thread(self):
        """
        Check if SWAP's control thread is has exited unexpectedly
        """
        return self.control.exit.is_set()

    @needs_auth
    def classify(self):
        """
        Receive a classification from Caesar and process it
        """
        logger.info('received request')

        # Return a 500 code if SWAP's thread has exited prematurely
        if self._check_thread():
            message = 'Exception in SWAP thread\n%s' % self.control.exception
            r = Response(message, status=500)
            return r

        # Parse json from request
        data = request.get_json()
        logger.debug('cl %s request %s', str(data['id']), str(request))

        if not self._is_recent_cl(data):
            # Process classification
            logger.info('Classification not recently received')
            logger.debug('received data %s', str(data))
            self.control.queue('classify', data, Requests.respond)
        else:
            # Filter duplicate classifications
            logger.info('Filtering duplicate classification')

        # return empty response
        return Response(status=204)

    @needs_auth
    def scores(self):
        """
        Return current score export
        """
        scores = self.control.scores()

        return jsonify(scores.full_dict())

    def _is_recent_cl(self, data):
        """
        Check if classification has recently been received

        Instance tracks the 10 most recent classifications received
        to filter out classifications that are sent twice.
        """
        # Check if cl id in recent list
        id_ = data['id']
        if id_ in self._recent_cl:
            return True

        # Cl is not recent. Add id to recent list
        self._recent_cl.append(id_)
        if len(self._recent_cl) > 10:
            self._recent_cl.pop(0)
        return False


def validate_config():
    if config.online_swap.project is None:
        raise config.ConfigError(
            'online_swap.name',
            'Project name cannot be None')


def init_threader(swap=None):
    validate_config()

    thread = ThreadedControl(swap_=swap)
    thread.start()
    logger.info('Finished launching swap thread')

    return thread


if __name__ == '__main__':
    control = init_threader()
    api = API(control)
    api.run()
