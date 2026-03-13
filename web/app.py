"""Flask 웹 서버"""
import math
import subprocess
import sys
import os
from flask import Flask, render_template, jsonify, request
from storage.database import init_db, get_notices, get_notice_with_attachments, count_notices


def create_app():
    app = Flask(__name__, template_folder='templates')
    init_db()

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/api/notices')
    def api_notices():
        source = request.args.get('source')           # 'mohw' | 'hira' | None
        from_date = request.args.get('from_date', request.args.get('from', '2026-03-01'))
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', request.args.get('limit', 50)))
        offset = (page - 1) * page_size

        total = count_notices(source=source, from_date=from_date)
        notices = get_notices(source=source, from_date=from_date, limit=page_size, offset=offset)
        pages = max(1, math.ceil(total / page_size))

        return jsonify({
            'notices': notices,
            'total': total,
            'page': page,
            'page_size': page_size,
            'pages': pages,
        })

    @app.route('/api/notices/<int:notice_id>')
    def api_notice_detail(notice_id):
        notice = get_notice_with_attachments(notice_id)
        return jsonify(notice)

    @app.route('/api/run/<task>', methods=['POST'])
    def api_run_task(task):
        if task not in ('crawl', 'summarize', 'all'):
            return jsonify({'error': 'invalid task'}), 400
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_py = os.path.join(project_root, 'main.py')
        proc = subprocess.Popen(
            [sys.executable, main_py, task],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        output, _ = proc.communicate()
        return jsonify({'exit_code': proc.returncode, 'output': output})

    return app
