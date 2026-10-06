from flask import Blueprint, Response, stream_with_context
from flask_user import current_user

from web.server.routes.views.authentication import authentication_required
from web.server.routes.views.dashboard import get_viewable_dashboard
from web.server.routes.views.page_renderer import (
    grid_dashboard_to_pdf,
    grid_dashboard_to_thumbnail,
    grid_dashboard_to_image,
)

FULL_DASHBOARD_CONTENT = 'application/pdf'
THUMBNAIL_CONTENT = 'image/png'
JPEG_CONTENT = 'image/jpeg'

# Every render is made as the signed-in caller, so public access never opens
# these routes to anonymous visitors.
render_route = authentication_required(is_api_request=True, force_authentication=True)


def response_wrapper(render_response, content_type):
    # Check for 500 status code and return our own Response object because
    # the Response object below doesn't catch internal server errors.
    # So far we do this only to catch the TimeoutError.
    if not render_response or render_response.status_code == 500:
        response = Response()
        response.status_code = 500
        return response

    headers = {'Content-Type': content_type}
    return Response(
        stream_with_context(render_response.iter_content(chunk_size=2048)),
        headers=headers,
    )


class PageRendererRouter:
    @render_route
    def grid_dashboard_to_pdf(self, locale=None, name=None, session_hash=''):
        dashboard = get_viewable_dashboard(name)
        return response_wrapper(
            grid_dashboard_to_pdf(
                locale,
                dashboard.slug,
                auth_user=current_user,
                session_hash=session_hash,
            ),
            FULL_DASHBOARD_CONTENT,
        )

    @render_route
    def grid_dashboard_to_thumbnail(self, locale=None, name=None):
        dashboard = get_viewable_dashboard(name)
        return response_wrapper(
            grid_dashboard_to_thumbnail(locale, dashboard.slug, auth_user=current_user),
            THUMBNAIL_CONTENT,
        )

    @render_route
    def grid_dashboard_to_image(self, locale=None, name=None, session_hash=''):
        dashboard = get_viewable_dashboard(name)
        return response_wrapper(
            grid_dashboard_to_image(
                locale,
                dashboard.slug,
                auth_user=current_user,
                session_hash=session_hash,
            ),
            JPEG_CONTENT,
        )

    def generate_blueprint(self):
        render_page = Blueprint('render_page', __name__, template_folder='templates')

        render_page.add_url_rule(
            '/dashboard/<name>/pdf', 'grid_dashboard_to_pdf', self.grid_dashboard_to_pdf
        )
        render_page.add_url_rule(
            '/<locale>/dashboard/<name>/pdf',
            'grid_dashboard_to_pdf',
            self.grid_dashboard_to_pdf,
        )

        render_page.add_url_rule(
            '/dashboard/<name>/png/thumbnail',
            'grid_dashboard_to_thumbnail',
            self.grid_dashboard_to_thumbnail,
        )
        render_page.add_url_rule(
            '/<locale>/dashboard/<name>/png/thumbnail',
            'grid_dashboard_to_thumbnail',
            self.grid_dashboard_to_thumbnail,
        )

        render_page.add_url_rule(
            '/dashboard/<name>/jpeg',
            'grid_dashboard_to_image',
            self.grid_dashboard_to_image,
        )
        render_page.add_url_rule(
            '/<locale>/dashboard/<name>/jpeg',
            'grid_dashboard_to_image',
            self.grid_dashboard_to_image,
        )

        render_page.add_url_rule(
            '/dashboard/<name>/<session_hash>/jpeg',
            'grid_dashboard_to_image_w_hash',
            self.grid_dashboard_to_image,
        )
        render_page.add_url_rule(
            '/<locale>/dashboard/<name>/<session_hash>/jpeg',
            'grid_dashboard_to_image_w_hash',
            self.grid_dashboard_to_image,
        )

        render_page.add_url_rule(
            '/dashboard/<name>/<session_hash>/pdf',
            'grid_dashboard_to_pdf_with_hash',
            self.grid_dashboard_to_pdf,
        )
        render_page.add_url_rule(
            '/<locale>/dashboard/<name>/<session_hash>/pdf',
            'grid_dashboard_to_pdf_with_hash',
            self.grid_dashboard_to_pdf,
        )

        return render_page
