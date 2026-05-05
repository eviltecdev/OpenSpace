import os
import platform
import shlex
import subprocess
import signal
import time
import json
import uuid
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify, send_file, abort, Response, g
import pyautogui
import threading
from io import BytesIO
import tempfile

from ruflo.utils.logging import Logger
from openspace.metrics.prometheus import (
    http_requests_total,
    http_request_duration_seconds,
    http_exceptions_total,
    openspace_readiness,
    openspace_active_tasks,
    record_exception,
    record_request,
    normalize_endpoint,
)
from openspace.runtime_state import get_execute_task_active
from ruflo.local_server.utils import AccessibilityHelper, ScreenshotHelper
from ruflo.local_server.platform_adapters import get_platform_adapter
from ruflo.local_server.health_checker import HealthChecker
from ruflo.local_server.feature_checker import FeatureChecker

platform_name = platform.system()

_HOME = os.path.realpath(os.path.expanduser("~"))
_ALLOWED_ROOTS = (_HOME, "/tmp")


def _validate_path(path: str) -> str:
    """Resolve path and ensure it stays within allowed roots.

    Raises ValueError if the resolved path escapes the allowed roots,
    preventing path-traversal attacks (e.g. ../../../../etc/passwd) and
    symlink-based escape attempts.
    """
    expanded = os.path.expanduser(path)
    resolved = os.path.realpath(expanded)

    # Compare realpath of both resolved path and allowed roots to prevent
    # symlink-based escape: symlink → parent allowed dir → ../../../etc/passwd
    resolved_allowed = [os.path.realpath(root) for root in _ALLOWED_ROOTS]

    if not any(resolved.startswith(root + os.sep) or resolved == root
               for root in resolved_allowed):
        raise ValueError(f"Access denied: path outside allowed directories: {resolved}")
    return resolved


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

pyautogui.PAUSE = 0
if platform_name == "Darwin":
    pyautogui.DARWIN_CATCH_UP_TIME = 0

logger = Logger.get_logger(__name__)

TIMEOUT = 1800
recording_process = None

if platform_name == "Windows":
    recording_path = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'recording.mp4')
else:
    recording_path = "/tmp/recording.mp4"

accessibility_helper = AccessibilityHelper()
screenshot_helper = ScreenshotHelper()
platform_adapter = get_platform_adapter()

feature_checker = FeatureChecker(
    platform_adapter=platform_adapter,
    accessibility_helper=accessibility_helper
)


def get_conda_activation_prefix(conda_env: str = None) -> str:
    """
    Generate platform-specific conda activation command prefix
    
    Args:
        conda_env: Conda environment name (e.g., 'myenv')
    
    Returns:
        Activation command prefix string, empty if no conda_env
    """
    if not conda_env:
        return ""
    
    if platform_name == "Windows":
        # Windows: use conda.bat or conda.exe
        # Try common conda installation paths
        conda_paths = [
            os.path.expandvars("%USERPROFILE%\\miniconda3\\Scripts\\activate.bat"),
            os.path.expandvars("%USERPROFILE%\\anaconda3\\Scripts\\activate.bat"),
            "C:\\ProgramData\\Miniconda3\\Scripts\\activate.bat",
            "C:\\ProgramData\\Anaconda3\\Scripts\\activate.bat",
        ]
        
        # Find first existing conda activate script
        activate_script = None
        for path in conda_paths:
            if os.path.exists(path):
                activate_script = path
                break
        
        if activate_script:
            return f'call "{activate_script}" {conda_env} && '
        else:
            # Fallback: assume conda is in PATH
            return f'conda activate {conda_env} && '
    
    else:
        # Linux/macOS: source conda.sh then activate
        conda_paths = [
            os.path.expanduser("~/miniconda3/etc/profile.d/conda.sh"),
            os.path.expanduser("~/anaconda3/etc/profile.d/conda.sh"),
            "/opt/conda/etc/profile.d/conda.sh",
            "/usr/local/miniconda3/etc/profile.d/conda.sh",
            "/usr/local/anaconda3/etc/profile.d/conda.sh",
        ]
        
        # Find first existing conda.sh
        conda_sh = None
        for path in conda_paths:
            if os.path.exists(path):
                conda_sh = path
                break
        
        if conda_sh:
            return f'source "{conda_sh}" && conda activate {conda_env} && '
        else:
            # Fallback: assume conda is already initialized in shell
            return f'conda activate {conda_env} && '


def wrap_script_with_conda(script: str, conda_env: str = None) -> str:
    """
    Wrap script with conda activation command.
    If conda is not available, returns original script without conda activation.
    """
    if not conda_env:
        return script
    
    if platform_name == "Windows":
        activation_prefix = get_conda_activation_prefix(conda_env)
        return f"{activation_prefix}{script}"
    else:
        conda_paths = [
            os.path.expanduser("~/miniconda3/etc/profile.d/conda.sh"),
            os.path.expanduser("~/anaconda3/etc/profile.d/conda.sh"),
            os.path.expanduser("~/opt/anaconda3/etc/profile.d/conda.sh"),
            "/opt/conda/etc/profile.d/conda.sh",
        ]
        
        conda_sh = None
        for path in conda_paths:
            if os.path.exists(path):
                conda_sh = path
                break
        
        if conda_sh:
            # Use bash -i -c to run interactively, or directly source conda.sh
            wrapped_script = f"""#!/bin/bash
# Initialize conda
if [ -f "{conda_sh}" ]; then
    . "{conda_sh}"
    conda activate {conda_env} 2>/dev/null || true
fi

# Run user script
{script}
"""
            return wrapped_script
        else:
            # Conda not found - log warning and execute script directly without conda
            logger.warning(f"Conda environment '{conda_env}' requested but conda not found. Executing with system Python.")
            return script


health_checker = None
_app_startup_time = time.time()


# Prometheus instrumentation hooks
@app.before_request
def before_request():
    """Record request start time and compute normalized endpoint."""
    g.start_time = time.time()

    # Compute normalized endpoint once, reuse in after_request and error handler
    g.metric_endpoint = normalize_endpoint(
        request.path,
        getattr(request.url_rule, 'rule', None),
    )

    # Update active task count gauge
    try:
        active_tasks = get_execute_task_active()
        openspace_active_tasks.set(active_tasks)
    except Exception as e:
        logger.warning(f"Failed to update active task count metric: {e}")


@app.after_request
def after_request(response):
    """Record request duration and status code metrics."""
    try:
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            method = request.method
            status = response.status_code
            endpoint = getattr(
                g,
                'metric_endpoint',
                normalize_endpoint(
                    request.path,
                    getattr(request.url_rule, 'rule', None),
                ),
            )

            # Record metrics (endpoint already normalized in before_request, or via fallback)
            record_request(endpoint, method, status, duration)
    except Exception as e:
        logger.warning(f"Failed to record request metrics: {e}")

    return response


@app.errorhandler(Exception)
def handle_exception(e):
    """Record exception metrics and re-raise."""
    try:
        endpoint = getattr(
            g,
            'metric_endpoint',
            normalize_endpoint(
                request.path,
                getattr(request.url_rule, 'rule', None),
            ),
        )
        record_exception(endpoint, type(e).__name__)
    except Exception as metric_error:
        logger.warning(f"Failed to record exception metric: {metric_error}")

    raise


@app.route('/', methods=['GET'])
def health_check():
    """Health check interface - return features information"""
    # Get features from health_checker
    if health_checker:
        features = health_checker.get_simple_features_dict()
    else:
        # Initial startup of health_checker may not have been initialized, fallback to feature_checker
        features = feature_checker.check_all_features(use_cache=True)
    
    return jsonify({
        'status': 'ok',
        'service': 'OpenSpace Desktop Server',
        'version': '1.0.0',
        'platform': platform_name,
        'features': features,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health():
    """Kubernetes liveness probe: always 200 if process is running."""
    return jsonify({'status': 'ok'}), 200

@app.route('/ready', methods=['GET'])
def ready():
    """Kubernetes readiness probe: 200 if ready to serve, 503 if not.

    GUARANTEED to return 200 or 503, never 500.
    Hard safety guard wraps entire handler.
    """
    try:
        # Stage 1: Get readiness state (safe by design)
        try:
            from openspace.runtime_state import get_is_ready
            is_ready = get_is_ready()
        except Exception:
            # Any import/access error → not ready
            is_ready = False

        # Stage 2: Update readiness gauge
        try:
            openspace_readiness.set(1 if is_ready else 0)
        except Exception as e:
            logger.warning(f"Failed to update readiness gauge: {e}")

        # Stage 3: Try to return JSON response
        try:
            if is_ready:
                return jsonify({'ready': True, 'reason': None}), 200
            else:
                return jsonify({'ready': False, 'reason': 'MCP server not ready or shutting down'}), 503
        except Exception:
            # If jsonify fails, return plain dict (Flask converts to JSON)
            if is_ready:
                return {'ready': True, 'reason': None}, 200
            else:
                return {'ready': False, 'reason': 'MCP server not ready or shutting down'}, 503

    except Exception:
        # Absolute final fallback: hardcoded response, no processing
        # This should never execute, but prevents any 500 response
        return Response('{"ready":false,"reason":"internal_error"}', status=503, mimetype='application/json')

@app.route('/status', methods=['GET'])
def status():
    """Diagnostics endpoint: uptime, initialization state, limiter state, cloud status.

    GUARANTEED to return 200, never 500.
    Hard safety guard wraps entire handler.
    """
    try:
        # Stage 1: Get uptime (always safe)
        uptime_seconds = time.time() - _app_startup_time

        # Stage 2: Get MCP server state via lightweight bridge
        openspace_initialized = False
        execute_task_active = 0
        search_skills_active = 0
        cloud_status = 'unknown'

        try:
            from openspace.runtime_state import (
                get_openspace_initialized,
                get_execute_task_active,
                get_search_skills_active,
                get_cloud_status,
            )

            openspace_initialized = get_openspace_initialized()
            execute_task_active = get_execute_task_active()
            search_skills_active = get_search_skills_active()
            cloud_status = get_cloud_status()
        except Exception:
            # Any error loading state → use safe defaults
            # (already set above)
            pass

        # Stage 3: Try to return JSON response
        try:
            return jsonify({
                'uptime_seconds': uptime_seconds,
                'openspace_initialized': openspace_initialized,
                'limiter': {
                    'execute_task_active': execute_task_active,
                    'search_skills_active': search_skills_active,
                },
                'cloud_status': cloud_status,
            }), 200
        except Exception:
            # If jsonify fails, return plain dict (Flask converts to JSON)
            return {
                'uptime_seconds': uptime_seconds,
                'openspace_initialized': openspace_initialized,
                'limiter': {
                    'execute_task_active': execute_task_active,
                    'search_skills_active': search_skills_active,
                },
                'cloud_status': cloud_status,
            }, 200

    except Exception:
        # Absolute final fallback: hardcoded response, no processing
        return Response('{"uptime_seconds":0,"openspace_initialized":false,"limiter":{"execute_task_active":0,"search_skills_active":0},"cloud_status":"unknown"}', status=200, mimetype='application/json')


@app.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus metrics endpoint.

    Exposes all collected metrics in Prometheus text format.
    """
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

        return Response(
            generate_latest(),
            mimetype=CONTENT_TYPE_LATEST
        )
    except Exception as e:
        logger.error(f"Failed to generate metrics: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to generate metrics'
        }), 500

@app.route('/platform', methods=['GET'])
def get_platform():
    info = {
        'system': platform_name,
        'release': platform.release(),
        'version': platform.version(),
        'machine': platform.machine(),
        'processor': platform.processor()
    }
    
    if platform_adapter and hasattr(platform_adapter, 'get_system_info'):
        info.update(platform_adapter.get_system_info())
    
    return jsonify(info)

def _execute_shell(command, timeout: int = 120) -> dict:
    """Execute a shell command synchronously.

    Args:
        command: Command as string or list
        timeout: Timeout in seconds

    Returns:
        Dict with status, output, error, returncode
    """
    shell = False  # Always false for security (no shell=True allowed)

    if isinstance(command, str):
        command = shlex.split(command)

    # Expand user directory
    if isinstance(command, list):
        for i, arg in enumerate(command):
            if arg.startswith("~/"):
                command[i] = os.path.expanduser(arg)

    try:
        if platform_name == "Windows":
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell,
                text=True,
                timeout=timeout,
            )

        return {
            'status': 'success',
            'output': result.stdout,
            'error': result.stderr,
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            'status': 'error',
            'message': f'Command timeout after {timeout} seconds'
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }


async def _execute_task_async(task: str, task_input: dict, timeout: int = 120) -> dict:
    """Execute a structured task asynchronously.

    Args:
        task: Task name (e.g., "list_directory", "read_file")
        task_input: Task input parameters as dict
        timeout: Timeout in seconds (not enforced at this layer)

    Returns:
        Dict with status and result or error
    """
    try:
        from ruflo.mcp_server import execute_task

        # execute_task expects a task description string.
        # For now, we'll pass the task name and input as a formatted instruction.
        task_instruction = f"Execute task: {task}\nInput: {json.dumps(task_input)}"

        result_str = await execute_task(task_instruction)

        # Try to parse the result as JSON
        try:
            result = json.loads(result_str)
            return {
                'status': 'success',
                'result': result
            }
        except json.JSONDecodeError:
            return {
                'status': 'success',
                'result': result_str
            }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }


def _execute_task_sync(task: str, task_input: dict, timeout: int = 120) -> dict:
    """Execute a structured task synchronously (wrapper for async).

    Args:
        task: Task name
        task_input: Task input parameters
        timeout: Timeout in seconds

    Returns:
        Dict with status and result or error
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_execute_task_async(task, task_input, timeout))
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }
    finally:
        loop.close()


@app.route('/execute', methods=['POST'])
@app.route('/setup/execute', methods=['POST'])
def execute_command():
    """Execute shell command or structured task based on type field.

    Request formats:
    - Shell: {"type": "shell", "command": "...", "timeout": 120}
    - Task: {"type": "task", "task": "list_directory", "input": {...}, "timeout": 120}
    """
    data = request.json
    if not data:
        return jsonify({
            'status': 'error',
            'message': 'Request body must be JSON'
        }), 400

    # Check for deprecated behavior (missing type field)
    request_type = data.get('type')
    if request_type is None:
        logger.warning(
            "Deprecated: /execute request missing 'type' field. "
            "Defaulting to 'shell'. This will be required in a future version. "
            "Use type='shell' or type='task' explicitly."
        )
        request_type = 'shell'

    timeout = data.get('timeout', 120)

    if request_type == 'shell':
        # Reject shell=True parameter for security
        if data.get('shell', False):
            return jsonify({
                'status': 'error',
                'message': 'shell=True is not allowed. Commands must be provided as arguments.'
            }), 400

        command = data.get('command', [])
        result = _execute_shell(command, timeout=timeout)

        if result.get('status') == 'error':
            return jsonify(result), 500
        return jsonify(result), 200

    elif request_type == 'task':
        task = data.get('task')
        if not task:
            return jsonify({
                'status': 'error',
                'message': 'task field is required for type=task'
            }), 400

        task_input = data.get('input', {})
        result = _execute_task_sync(task, task_input, timeout=timeout)

        if result.get('status') == 'error':
            return jsonify(result), 500
        return jsonify(result), 200

    else:
        return jsonify({
            'status': 'error',
            'message': f'Unknown type: {request_type}. Supported: shell, task'
        }), 400

@app.route('/execute_with_verification', methods=['POST'])
@app.route('/setup/execute_with_verification', methods=['POST'])
def execute_command_with_verification():
    """Execute command and verify the result based on provided verification criteria"""
    data = request.json
    shell = data.get('shell', False)

    # Reject shell=True to prevent shell injection attacks.
    if shell:
        return jsonify({
            'status': 'error',
            'message': 'shell=True is not allowed. Provide command as a list of arguments.'
        }), 400

    command = data.get('command', [])
    verification = data.get('verification', {})
    max_wait_time = data.get('max_wait_time', 10) # Maximum wait time in seconds
    check_interval = data.get('check_interval', 1) # Check interval in seconds
    
    if isinstance(command, str) and not shell:
        command = shlex.split(command)
    
    # Expand user directory
    if isinstance(command, list):
        for i, arg in enumerate(command):
            if arg.startswith("~/"):
                command[i] = os.path.expanduser(arg)
    
    # Execute the main command
    try:
        if platform_name == "Windows":
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell,
                text=True,
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell,
                text=True,
                timeout=120,
            )
        
        # If no verification is needed, return immediately
        if not verification:
            return jsonify({
                'status': 'success',
                'output': result.stdout,
                'error': result.stderr,
                'returncode': result.returncode
            })
        
        # Wait and verify the result
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            verification_passed = True
            
            # Check window existence if specified
            if 'window_exists' in verification:
                window_name = verification['window_exists']
                try:
                    if platform_name == 'Linux':
                        wmctrl_result = subprocess.run(
                            ['wmctrl', '-l'],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        if window_name.lower() not in wmctrl_result.stdout.lower():
                            verification_passed = False
                    elif platform_adapter:
                        # Use platform adapter to check window existence
                        windows = platform_adapter.list_windows() if hasattr(platform_adapter, 'list_windows') else []
                        if not any(window_name.lower() in str(w).lower() for w in windows):
                            verification_passed = False
                except:
                    verification_passed = False
            
            # Check command execution if specified
            if 'command_success' in verification:
                verify_cmd = verification['command_success']
                try:
                    # Verify command must be a list to prevent shell injection
                    if isinstance(verify_cmd, str):
                        verify_cmd = shlex.split(verify_cmd)
                    verify_result = subprocess.run(
                        verify_cmd,
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if verify_result.returncode != 0:
                        verification_passed = False
                except Exception:
                    verification_passed = False
            
            if verification_passed:
                return jsonify({
                    'status': 'success',
                    'output': result.stdout,
                    'error': result.stderr,
                    'returncode': result.returncode,
                    'verification': 'passed',
                    'wait_time': time.time() - start_time
                })
            
            time.sleep(check_interval)
        
        # Verification failed
        return jsonify({
            'status': 'verification_failed',
            'output': result.stdout,
            'error': result.stderr,
            'returncode': result.returncode,
            'verification': 'failed',
            'wait_time': max_wait_time
        }), 500
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def _get_machine_architecture() -> str:
    """Get the machine architecture, e.g., x86_64, arm64, aarch64, i386, etc.
    Returns 'amd' for x86/AMD architectures, 'arm' for ARM architectures, or 'unknown'.
    """
    architecture = platform.machine().lower()
    if architecture in ['amd32', 'amd64', 'x86', 'x86_64', 'x86-64', 'x64', 'i386', 'i686']:
        return 'amd'
    elif architecture in ['arm64', 'aarch64', 'aarch32']:
        return 'arm'
    else:
        return 'unknown'

@app.route('/setup/launch', methods=["POST"])
def launch_app():
    data = request.json
    shell = data.get("shell", False)

    # Reject shell=True to prevent shell injection attacks.
    if shell:
        return jsonify({
            'status': 'error',
            'message': 'shell=True is not allowed. Provide command as a list of arguments.'
        }), 400

    command = data.get("command", [])
    
    if isinstance(command, str) and not shell:
        command = shlex.split(command)
    
    # Expand user directory
    if isinstance(command, list):
        for i, arg in enumerate(command):
            if arg.startswith("~/"):
                command[i] = os.path.expanduser(arg)
    
    try:
        # ARM architecture compatibility: replace google-chrome with chromium
        # ARM64 Chrome is not available yet, can only use Chromium
        if isinstance(command, list) and 'google-chrome' in command and _get_machine_architecture() == 'arm':
            index = command.index('google-chrome')
            command[index] = 'chromium'
            logger.info("ARM architecture detected: replacing 'google-chrome' with 'chromium'")

        # Launch with hygiene: redirect stdout/stderr to avoid deadlock/pipe exhaustion,
        # and close_fds to avoid resource leaks.
        subprocess.Popen(
            command,
            shell=shell,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True
        )
        cmd_str = command if shell else " ".join(command)
        logger.info(f"Application launched successfully: {cmd_str}")
        return jsonify({
            'status': 'success',
            'message': f'{cmd_str} launched successfully'
        })
    except Exception as e:
        logger.error(f"Application launch failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route("/run_python", methods=['POST'])
def run_python():
    data = request.json
    code = data.get('code', None)
    timeout = data.get('timeout', 30)
    working_dir = data.get('working_dir', None)
    env = data.get('env', None)
    conda_env = data.get('conda_env', None)
    
    if not code:
        return jsonify({'status': 'error', 'message': 'Code not supplied!'}), 400
    
    # Generate unique filename
    if platform_name == "Windows":
        temp_filename = os.path.join(tempfile.gettempdir(), f"python_exec_{uuid.uuid4().hex}.py")
    else:
        temp_filename = f"/tmp/python_exec_{uuid.uuid4().hex}.py"
    
    try:
        with open(temp_filename, 'w') as f:
            f.write(code)
        
        # Prepare environment variables
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        
        # If conda_env is specified, try to use bash/cmd to activate and run
        # If conda is not available, fall back to system Python
        if conda_env:
            activation_cmd = get_conda_activation_prefix(conda_env)
            # Check if conda activation command is empty (conda not found)
            if not activation_cmd:
                logger.warning(f"Conda environment '{conda_env}' requested but conda not found. Using system Python.")
                conda_env = None  # Disable conda and use default path
        
        if conda_env and get_conda_activation_prefix(conda_env):
            if platform_name == "Windows":
                # Windows: use cmd with activation
                activation_cmd = get_conda_activation_prefix(conda_env)
                full_cmd = f'{activation_cmd}python "{temp_filename}"'
                result = subprocess.run(
                    ['cmd', '/c', full_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout,
                    cwd=working_dir or os.getcwd(),
                    env=exec_env
                )
            else:
                # Linux/macOS: use bash with activation
                activation_cmd = get_conda_activation_prefix(conda_env)
                full_cmd = f'{activation_cmd}python3 "{temp_filename}"'
                result = subprocess.run(
                    ['/bin/bash', '-c', full_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout,
                    cwd=working_dir or os.getcwd(),
                    env=exec_env
                )
        else:
            # No conda activation needed
            python_cmd = 'python' if platform_name == "Windows" else 'python3'
            result = subprocess.run(
                [python_cmd, temp_filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                cwd=working_dir or os.getcwd(),
                env=exec_env
            )
        
        os.remove(temp_filename)
        
        output = result.stdout + result.stderr
        
        return jsonify({
            'status': 'success' if result.returncode == 0 else 'error',
            'content': output or "Code executed successfully (no output)",
            'returncode': result.returncode
        })
        
    except subprocess.TimeoutExpired:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        return jsonify({
            'status': 'error',
            'message': f'Execution timeout after {timeout} seconds'
        }), 408
    except Exception as e:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route("/run_bash_script", methods=['POST'])
def run_bash_script():
    data = request.json
    script = data.get('script', None)
    timeout = data.get('timeout', 30)
    working_dir = data.get('working_dir', None)
    env = data.get('env', None)
    conda_env = data.get('conda_env', None)
    
    if not script:
        return jsonify({'status': 'error', 'message': 'Script not supplied!'}), 400
    
    # Generate unique filename
    if platform_name == "Windows":
        temp_filename = os.path.join(tempfile.gettempdir(), f"bash_exec_{uuid.uuid4().hex}.sh")
    else:
        temp_filename = f"/tmp/bash_exec_{uuid.uuid4().hex}.sh"
    
    try:
        # Wrap script with conda activation if needed
        final_script = wrap_script_with_conda(script, conda_env)
        
        with open(temp_filename, 'w') as f:
            f.write(final_script)
        
        os.chmod(temp_filename, 0o755)
        
        if platform_name == "Windows":
            shell_cmd = ['bash', temp_filename]
        else:
            shell_cmd = ['/bin/bash', temp_filename]
        
        # Prepare environment variables
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        
        result = subprocess.run(
            shell_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            cwd=working_dir or os.getcwd(),
            env=exec_env
        )
        
        os.unlink(temp_filename)
        
        return jsonify({
            'status': 'success' if result.returncode == 0 else 'error',
            'output': result.stdout,
            'error': "",
            'returncode': result.returncode
        })
        
    except subprocess.TimeoutExpired:
        if os.path.exists(temp_filename):
            os.unlink(temp_filename)
        return jsonify({
            'status': 'error',
            'output': f'Script execution timed out after {timeout} seconds',
            'error': "",
            'returncode': -1
        }), 500
    except Exception as e:
        if os.path.exists(temp_filename):
            try:
                os.unlink(temp_filename)
            except:
                pass
        return jsonify({
            'status': 'error',
            'output': f'Failed to execute script: {str(e)}',
            'error': "",
            'returncode': -1
        }), 500
        
@app.route('/screenshot', methods=['GET'])
def capture_screen_with_cursor():
    """Capture screenshot (including mouse cursor)"""
    try:
        buf = BytesIO()
        tmp_path = os.path.join(tempfile.gettempdir(), f"screenshot_{uuid.uuid4().hex}.png")
        if screenshot_helper.capture(tmp_path, with_cursor=True):
            with open(tmp_path, 'rb') as f:
                buf.write(f.read())
            os.remove(tmp_path)            
            buf.seek(0)
            return send_file(buf, mimetype='image/png')
        else:
            return jsonify({'status':'error','message':'Screenshot failed'}), 500
        
    except Exception as e:
        logger.error(f"Screenshot failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/cursor_position', methods=['GET'])
def get_cursor_position():
    """Get cursor position"""
    try:
        x, y = screenshot_helper.get_cursor_position()
        return jsonify({'x': x, 'y': y, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/screen_size', methods=['POST', 'GET'])
def get_screen_size():
    """Get screen size"""
    try:
        width, height = screenshot_helper.get_screen_size()
        return jsonify({'width': width, 'height': height, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Accessibility Tree
@app.route("/accessibility", methods=["GET"])
def get_accessibility_tree():
    """Get accessibility tree"""
    try:
        max_depth = request.args.get('max_depth', 10, type=int)
        tree = accessibility_helper.get_tree(max_depth=max_depth)
        return jsonify(tree)
    except Exception as e:
        logger.error(f"Failed to get accessibility tree: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# File Operations
@app.route('/list_directory', methods=['POST'])
def list_directory():
    """List directory contents"""
    data = request.json
    path = data.get('path', '.')
    
    try:
        path = _validate_path(path)
        items = []

        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            items.append({
                'name': item,
                'is_dir': os.path.isdir(item_path),
                'is_file': os.path.isfile(item_path),
                'size': os.path.getsize(item_path) if os.path.isfile(item_path) else None
            })
        
        return jsonify({
            'status': 'success',
            'path': path,
            'items': items
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/file', methods=['POST'])
def file_operation():
    """File operations"""
    data = request.json
    operation = data.get('operation', 'read')
    path = data.get('path')
    
    if not path:
        return jsonify({'status': 'error', 'message': 'Path required'}), 400

    try:
        path = _validate_path(path)
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 403

    try:
        if operation == 'read':
            with open(path, 'r') as f:
                content = f.read()
            return jsonify({
                'status': 'success',
                'content': content
            })
        elif operation == 'exists':
            exists = os.path.exists(path)
            return jsonify({
                'status': 'success',
                'exists': exists
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'Unknown operation: {operation}'
            }), 400
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/desktop_path', methods=['POST', 'GET'])
def get_desktop_path():
    """Get desktop path"""
    try:
        desktop = os.path.expanduser("~/Desktop")
        return jsonify({
            'status': 'success',
            'path': desktop
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route("/setup/activate_window", methods=['POST'])
def activate_window():
    """Activate window"""
    data = request.json
    window_name = data.get("window_name")
    strict = data.get("strict", False)
    by_class_name = data.get("by_class", False)
    
    if not window_name:
        return jsonify({'status': 'error', 'message': 'window_name required'}), 400
    
    try:
        if platform_adapter and hasattr(platform_adapter, 'activate_window'):
            result = platform_adapter.activate_window(window_name, strict=strict)
            if result['status'] == 'success':
                return jsonify(result)
            else:
                return jsonify(result), 400
        else:
            return jsonify({
                'status': 'error',
                'message': f'Window activation not supported on {platform_name}'
            }), 501
    except Exception as e:
        logger.error(f"Window activation failed: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route("/setup/close_window", methods=["POST"])
def close_window():
    """Close window"""
    data = request.json
    window_name = data.get("window_name")
    strict = data.get("strict", False)
    by_class_name = data.get("by_class", False)
    
    if not window_name:
        return jsonify({'status': 'error', 'message': 'window_name required'}), 400
    
    try:
        if platform_adapter and hasattr(platform_adapter, 'close_window'):
            result = platform_adapter.close_window(window_name, strict=strict)
            if result['status'] == 'success':
                return jsonify(result)
            else:
                return jsonify(result), 404
        else:
            return jsonify({
                'status': 'error',
                'message': f'Window closing not supported on {platform_name}'
            }), 501
    except Exception as e:
        logger.error(f"Window closing failed: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/window_size', methods=['POST'])
def get_window_size():
    """Get window size"""
    try:
        width, height = screenshot_helper.get_screen_size()
        return jsonify({
            'status': 'success',
            'width': width,
            'height': height
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/wallpaper', methods=['POST'])
@app.route('/setup/change_wallpaper', methods=['POST'])
def set_wallpaper():
    """Set wallpaper"""
    data = request.json
    image_path = data.get('path')
    
    if not image_path:
        return jsonify({'status': 'error', 'message': 'path required'}), 400
    
    try:
        if platform_adapter and hasattr(platform_adapter, 'set_wallpaper'):
            result = platform_adapter.set_wallpaper(image_path)
            if result['status'] == 'success':
                return jsonify(result)
            else:
                return jsonify(result), 400
        else:
            return jsonify({
                'status': 'error',
                'message': f'Wallpaper setting not supported on {platform_name}'
            }), 501
    except Exception as e:
        logger.error(f"Failed to set wallpaper: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Screen Recording
@app.route('/start_recording', methods=['POST'])
def start_recording():
    """Start screen recording (supports Linux, macOS, Windows).

    Ensures recording_process is None on both success and failure,
    making state predictable for concurrent/retry scenarios.
    """
    global recording_process

    # Check if platform adapter supports recording
    if not platform_adapter or not hasattr(platform_adapter, 'start_recording'):
        return jsonify({
            'status': 'error',
            'message': f'Recording not supported on {platform_name}'
        }), 501

    # Check if recording is already in progress (idempotent check).
    # Use poll() safely: if process doesn't exist, poll() returns non-None.
    if recording_process:
        poll_result = recording_process.poll()
        if poll_result is None:
            # Process still running
            return jsonify({
                'status': 'error',
                'message': 'Recording is already in progress.'
            }), 400
        # Process exited; clear stale reference
        recording_process = None

    # Clean up old recording file
    if os.path.exists(recording_path):
        try:
            os.remove(recording_path)
        except OSError as e:
            logger.error(f"Cannot delete old recording file: {e}")

    try:
        # Use platform adapter to start recording
        result = platform_adapter.start_recording(recording_path)

        if result['status'] == 'success':
            recording_process = result.get('process')
            logger.info("Recording started successfully")
            return jsonify({
                'status': 'success',
                'message': 'Recording started'
            })
        else:
            # Ensure process is cleared even if platform adapter returns error
            recording_process = None
            error_msg = result.get('message', 'Unknown error')
            logger.error(f"Failed to start recording: {error_msg}")
            # Sanitize error message: don't leak platform-specific details
            return jsonify({
                'status': 'error',
                'message': 'Failed to start recording'
            }), 500

    except Exception as e:
        # Ensure recording_process is always cleared on exception
        recording_process = None
        logger.error(f"Failed to start recording: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/end_recording', methods=['POST'])
def end_recording():
    """End screen recording (supports Linux, macOS, Windows).

    Idempotent cleanup: always leaves recording_process = None
    so that retried calls or concurrent access don't corrupt state.
    """
    global recording_process

    # Check if recording is in progress (idempotent guard).
    if not recording_process:
        return jsonify({
            'status': 'error',
            'message': 'No recording in progress'
        }), 400

    # Verify process still alive. If poll() != None, process exited (stale reference).
    if recording_process.poll() is not None:
        recording_process = None
        return jsonify({
            'status': 'error',
            'message': 'No recording in progress'
        }), 400

    try:
        # Use platform adapter to stop recording
        if platform_adapter and hasattr(platform_adapter, 'stop_recording'):
            try:
                result = platform_adapter.stop_recording(recording_process)
                if result['status'] != 'success':
                    error_msg = result.get('message', 'Unknown error')
                    logger.error(f"Failed to stop recording: {error_msg}")
                    # Sanitize error message: don't leak platform-specific details
                    return jsonify({
                        'status': 'error',
                        'message': 'Failed to stop recording'
                    }), 500
            finally:
                # Ensure process is cleared regardless of adapter result
                recording_process = None
        else:
            # Fallback: terminate process directly (idempotent cleanup)
            try:
                try:
                    recording_process.send_signal(signal.SIGINT)
                    recording_process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    logger.warning("ffmpeg not responding, force terminating")
                    recording_process.kill()
                    recording_process.wait()
                except Exception as cleanup_err:
                    logger.warning(f"Error cleaning up recording process: {cleanup_err}")
            finally:
                # Always clear process reference
                recording_process = None

        # Check if recording file exists
        # Wait for ffmpeg to write file header
        for _ in range(10):
            if os.path.exists(recording_path) and os.path.getsize(recording_path) > 0:
                break
            time.sleep(0.5)

        if os.path.exists(recording_path) and os.path.getsize(recording_path) > 0:
            logger.info("Recording ended, file saved")
            return send_file(recording_path, as_attachment=True)
        else:
            logger.error("Recording file is missing or empty")
            return abort(500, description="Recording file is missing or empty")

    except Exception as e:
        logger.error(f"Failed to end recording: {str(e)}")
        # Ensure process is cleared before returning error (idempotent cleanup)
        if recording_process:
            try:
                # Final safety cleanup: kill process if still running
                if recording_process.poll() is None:
                    recording_process.kill()
                    recording_process.wait(timeout=5)
            except Exception as kill_err:
                logger.warning(f"Error killing recording process during exception: {kill_err}")
        recording_process = None
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/terminal', methods=['GET'])
def get_terminal_output():
    """Get terminal output (supports Linux, macOS, Windows)"""
    try:
        if platform_adapter and hasattr(platform_adapter, 'get_terminal_output'):
            output = platform_adapter.get_terminal_output()
            if output:
                return jsonify({'output': output, 'status': 'success'})
            else:
                return jsonify({
                    'status': 'error',
                    'message': f'No terminal output available on {platform_name}',
                    'platform_note': 'Make sure a terminal window is open and active'
                }), 404
        else:
            return jsonify({
                'status': 'error',
                'message': f'Terminal output not supported on {platform_name}'
            }), 501
    except Exception as e:
        logger.error(f"Failed to get terminal output: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route("/setup/upload", methods=["POST"])
def upload_file():
    """Upload file"""
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No file selected'}), 400
    
    try:
        # Get target path
        target_path = request.form.get('path', os.path.expanduser('~/Desktop'))
        target_path = os.path.expanduser(target_path)
        
        # Ensure directory exists
        os.makedirs(target_path, exist_ok=True)
        
        # Save file
        file_path = os.path.join(target_path, file.filename)
        file.save(file_path)
        
        logger.info(f"File uploaded successfully: {file_path}")
        return jsonify({
            'status': 'success',
            'path': file_path,
            'message': 'File uploaded successfully'
        })
    except Exception as e:
        logger.error(f"File upload failed: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route("/setup/download_file", methods=["POST"])
def download_file():
    """Download file"""
    data = request.json
    path = data.get('path')
    
    if not path:
        return jsonify({'status': 'error', 'message': 'path required'}), 400
    
    try:
        path = os.path.expanduser(path)
        
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': f'File not found: {path}'}), 404
        
        return send_file(path, as_attachment=True)
    except Exception as e:
        logger.error(f"File download failed: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route("/setup/open_file", methods=['POST'])
def open_file():
    """Open file (using system default application)"""
    data = request.json
    path = data.get('path')
    
    if not path:
        return jsonify({'status': 'error', 'message': 'path required'}), 400
    
    try:
        path = os.path.expanduser(path)
        
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': f'File not found: {path}'}), 404
        
        if platform_name == "Darwin":
            subprocess.Popen(['open', path])
        elif platform_name == "Linux":
            subprocess.Popen(['xdg-open', path])
        elif platform_name == "Windows":
            os.startfile(path)
        
        logger.info(f"File opened successfully: {path}")
        return jsonify({
            'status': 'success',
            'message': f'File opened: {path}'
        })
    except Exception as e:
        logger.error(f"File opening failed: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def print_banner(host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
    """Print startup banner with server information"""
    from ruflo.utils.display import print_banner as display_banner, print_section, print_separator, colorize
    
    # STARTUP INFORMATION
    display_banner("OpenSpace · Local Server")
    
    server_url = f"http://{host}:{port}"
    
    # Server section
    info_lines = [
        colorize(server_url, 'g', bold=True),
    ]
    if host == '0.0.0.0':
        info_lines.append(f"{colorize('Listening on all interfaces', 'gr')} {colorize('(0.0.0.0:' + str(port) + ')', 'y')}")
    info_lines.append(f"{colorize(platform_name, 'gr')} · {colorize('Debug' if debug else 'Production', 'y' if debug else 'g')}")
    
    print_section("Server", info_lines)
    
    print()
    print_separator()
    print(f"  {colorize('Press Ctrl+C to stop', 'gr')}")
    print()

def run_health_check_async():
    """Asynchronous running health check"""
    def _run():
        from ruflo.utils.display import colorize
        time.sleep(2)
        
        print(colorize("\n  - Starting health check...\n", 'c', bold=True))
        
        results = health_checker.check_all(test_endpoints=True)
        
        health_checker.print_results(results, show_endpoint_details=False)
        
        summary = health_checker.get_summary()
        logger.info(f"Health check completed: {summary['fully_available']}/{summary['total']} fully available")
    
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

_DEFAULT_PORT = int(os.environ.get("OPENSPACE_LOCAL_PORT", 5757))


def run_server(host: str = "127.0.0.1", port: int = _DEFAULT_PORT, debug: bool = False):
    """
    Start desktop control server
    
    Args:
        host: Listening address (127.0.0.1 for local, 0.0.0.0 for all interfaces)
        port: Listening port
        debug: Debug mode (display detailed logs)
    """
    global health_checker
    
    # Initialize health_checker
    base_url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}"
    health_checker = HealthChecker(feature_checker, base_url, auto_cleanup=False)
    
    print_banner(host, port, debug)

    if not debug:
        run_health_check_async()
    
    app.run(host=host, port=port, debug=debug, threaded=True)

def main():
    import argparse
    from ruflo.config.utils import get_config_value
    
    parser = argparse.ArgumentParser(
        description='OpenSpace Local Server - Desktop Control Server'
    )
    parser.add_argument('--host', type=str, default='127.0.0.1',
                       help='Server host (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=_DEFAULT_PORT,
                       help=f'Server port (default: {_DEFAULT_PORT}, override: OPENSPACE_LOCAL_PORT)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode')
    parser.add_argument('--config', type=str,
                       help='Path to config.json file')
    
    args = parser.parse_args()
    
    config_path = args.config
    if not config_path:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                server_config = get_config_value(config, 'server', {})
                
                host = args.host if args.host != '127.0.0.1' else get_config_value(server_config, 'host', '127.0.0.1')
                port = args.port if args.port != _DEFAULT_PORT else get_config_value(server_config, 'port', _DEFAULT_PORT)
                debug = args.debug or get_config_value(server_config, 'debug', False)
                
                run_server(host=host, port=port, debug=debug)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            run_server(host=args.host, port=args.port, debug=args.debug)
    else:
        run_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()