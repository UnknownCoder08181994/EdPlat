from flask import Blueprint, request, jsonify
from services.project_service import ProjectService

projects_bp = Blueprint('projects', __name__)

@projects_bp.route('/api/projects', methods=['GET'])
def list_projects():
    projects = ProjectService.list_projects()
    return jsonify(projects)

@projects_bp.route('/api/projects', methods=['POST'])
def create_project():
    data = request.json
    name = data.get('name')
    path = data.get('path')

    if not name or not path:
        return jsonify({"error": "Name and path are required"}), 400

    project = ProjectService.create_project(name, path)
    return jsonify(project), 201

@projects_bp.route('/api/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    try:
        ProjectService.delete_project(project_id)
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
