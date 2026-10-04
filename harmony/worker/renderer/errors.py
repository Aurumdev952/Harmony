class RenderError(Exception):
    '''A render that failed for a reason the caller may be told about.'''

    status = 500
    code = 'internal'


class InvalidRenderRequest(RenderError):
    status = 400
    code = 'invalid_request'


class RenderTimeout(RenderError):
    status = 504
    code = 'render_timeout'


class PageFailed(RenderError):
    '''The dashboard page did not load or never signalled that its tiles loaded.'''

    status = 502
    code = 'page_failed'


class OutputTooLarge(RenderError):
    status = 502
    code = 'output_too_large'
