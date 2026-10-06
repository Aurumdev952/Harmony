from flask import Blueprint, Response, request
from flask_user import current_user

from web.server.routes.views.authentication import authentication_required
from web.server.routes.views.dashboard import get_viewable_dashboard
from web.server.routes.views.page_renderer import (
    grid_dashboard_to_pdf,
    grid_dashboard_to_thumbnail,
    grid_dashboard_to_image,
)

# Every render is made as the signed-in caller, so public access never opens
# these routes to anonymous visitors.
render_route = authentication_required(is_api_request=True, force_authentication=True)


def response_wrapper(rendered):
    if rendered is None:
        return Response(status=500)
    return Response(rendered.content, content_type=rendered.content_type)


class PageRendererRouter:
    @render_route
    def grid_dashboard_to_pdf(self, locale=None, name=None, session_hash=''):
        dashboard = get_viewable_dashboard(name)
        return response_wrapper(
            grid_dashboard_to_pdf(
                locale,
                dashboard.slug,
                auth_user_email=current_user.username,
                session_hash=session_hash,
                request_args=request.args,
            )
        )

    @render_route
    def grid_dashboard_to_thumbnail(self, locale=None, name=None):
        dashboard = get_viewable_dashboard(name)
        return response_wrapper(
            grid_dashboard_to_thumbnail(
                locale, dashboard.slug, auth_user_email=current_user.username
            )
        )

    @render_route
    def grid_dashboard_to_image(self, locale=None, name=None, session_hash=''):
        dashboard = get_viewable_dashboard(name)
        return response_wrapper(
            grid_dashboard_to_image(
                locale,
                dashboard.slug,
                auth_user_email=current_user.username,
                session_hash=session_hash,
                request_args=request.args,
            )
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
