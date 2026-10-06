from flask import request
from flask_potion.routes import Route
from flask_potion.resource import Resource

from web.server.redis.thumbnail_storage_service import retrieve_item
from web.server.routes.views.authentication import authentication_required
from web.server.routes.views.dashboard import get_viewable_dashboard


class ThumbnailStorageResource(Resource):
    class Meta:
        name = 'storage'

    @Route.GET('/retrieve', title='Retrieve value from redis.')
    @authentication_required(is_api_request=True, force_authentication=True)
    def retrieve_from_storage(self):
        dashboard = get_viewable_dashboard(request.args.get('key'))
        return retrieve_item(dashboard)


RESOURCE_TYPES = [ThumbnailStorageResource]
