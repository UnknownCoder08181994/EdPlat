import os
from flask import Flask, render_template, request, jsonify, abort
from backend.qa.engine import resolve_query, resolve_by_answer_id, get_autocomplete
from backend.qa.chips import CHIPS
from backend.modules import get_module, get_practice

app = Flask(
    __name__,
    static_folder='frontend/static',
    template_folder='frontend/templates',
)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# -- Cache-busting helper for video URLs -----------------------------------
# Appends ?v=<mtime> so browsers refetch after re-encodes.

@app.context_processor
def video_cache_buster():
    def vid_url(filename):
        """Return /static/videos/<filename>?v=<mtime> for cache-busting."""
        if not filename:
            return ''
        path = os.path.join(app.static_folder, 'videos', filename)
        try:
            mtime = int(os.path.getmtime(path))
        except OSError:
            mtime = 0
        return f'/static/videos/{filename}?v={mtime}'
    return dict(vid_url=vid_url)

# -- Cache headers for static assets (videos get aggressive caching) ------

@app.after_request
def add_cache_headers(response):
    if request.path.startswith('/static/videos/'):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif request.path.startswith('/static/css/') or request.path.startswith('/static/js/'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    elif request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache'
    return response

# -- Favicon -------------------------------------------------------

@app.route('/favicon.ico')
def favicon():
    return '', 204

# -- Page routes ---------------------------------------------------

@app.route('/')
def index():
    return render_template('base.html')

@app.route('/modules')
def modules():
    return render_template('modules.html')

@app.route('/modules/<slug>')
def module_detail(slug):
    module = get_module(slug)
    if not module:
        abort(404)
    return render_template('module_detail.html', module=module, slug=slug)

@app.route('/modules/<slug>/<section_id>')
def module_viewer(slug, section_id):
    module = get_module(slug)
    if not module:
        abort(404)
    # Find the specific section object
    section = None
    for s in module.get('sections', []):
        if s['id'] == section_id:
            section = s
            break
    if not section:
        abort(404)
    return render_template('module_viewer.html', module=module, slug=slug, section_id=section_id, section=section)

@app.route('/tutorials')
def tutorials():
    return render_template('practice.html')

@app.route('/tutorials/<slug>/<section_id>')
def tutorials_viewer(slug, section_id):
    module = get_practice(slug)
    if not module:
        abort(404)
    section = None
    for s in module.get('sections', []):
        if s['id'] == section_id:
            section = s
            break
    if not section:
        abort(404)
    return render_template('module_viewer.html', module=module, slug=slug,
                           section_id=section_id, section=section, back_url='/tutorials')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

# -- Chat API routes -----------------------------------------------

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({'type': 'noMatch'}), 400
    message = data.get('message', '')
    pending = data.get('pendingFollowUp', None)
    module_slug = data.get('moduleSlug', None)
    result = resolve_query(message, pending, module_slug)
    return jsonify(result)

@app.route('/api/chat/resolve', methods=['POST'])
def api_chat_resolve():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({'type': 'noMatch'}), 400
    answer_id = data.get('answerId', '')
    result = resolve_by_answer_id(answer_id)
    return jsonify(result)

@app.route('/api/suggestions')
def api_suggestions():
    q = request.args.get('q', '')
    module_slug = request.args.get('module', None)
    results = get_autocomplete(q, module_slug=module_slug)
    return jsonify(results)

@app.route('/api/chips')
def api_chips():
    return jsonify(CHIPS)

if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)
