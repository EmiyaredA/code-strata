"""Explicit, checksum-pinned private runtime installation and bounded rendering."""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import zipfile

from .plantuml import serialize, sanitize_svg, VERSION

LOCK = json.loads(Path(__file__).with_name('uml-runtime-lock.json').read_text())


def runtime_root():
    if os.environ.get('CODE_STRATA_UML_RUNTIME'):
        return Path(os.environ['CODE_STRATA_UML_RUNTIME']).expanduser()
    base = Path.home() / ('Library/Caches' if platform.system() == 'Darwin' else 'AppData/Local' if os.name == 'nt' else '.cache')
    return base / 'code-strata' / 'uml-runtime'


def platform_key():
    arch = {'aarch64':'arm64', 'arm64':'arm64', 'x86_64':'x64', 'AMD64':'x64'}.get(platform.machine(), platform.machine())
    return platform.system().lower()+'-'+arch


def download(package, destination, progress=lambda *_: None):
    digest, total = hashlib.sha256(), 0
    request = urllib.request.Request(package['url'], headers={'User-Agent':'code-strata-runtime/1'})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open('wb') as stream:
        if not response.geturl().startswith('https://'):
            raise ValueError('运行时下载必须使用 HTTPS')
        size = int(response.headers.get('Content-Length', 0))
        while chunk := response.read(256*1024):
            total += len(chunk)
            if total > 220_000_000:
                raise ValueError('运行时发行包超过预算')
            digest.update(chunk); stream.write(chunk)
            progress(total, size)
    if digest.hexdigest() != package['sha256']:
        raise ValueError('运行时校验失败：SHA-256 不匹配')


def cached_download(package, directory, progress):
    directory.mkdir(parents=True, exist_ok=True)
    suffix = package.get('archive', '.jar')
    target = directory / (package['sha256'] + suffix)
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == package['sha256']:
        return target
    temporary = target.with_suffix(target.suffix+'.part')
    try:
        download(package, temporary, progress)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def extract(archive, destination):
    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not (destination/name).resolve().is_relative_to(destination.resolve()):
                    raise ValueError('运行时归档路径无效')
            bundle.extractall(destination)
    else:
        with tarfile.open(archive) as bundle:
            # Python's data filter rejects traversal, unsafe links and devices.
            bundle.extractall(destination, filter='data')


class UmlRuntime:
    def __init__(self, root=None):
        self.root = Path(root) if root else runtime_root()
        self.lock, self.slots = threading.RLock(), threading.BoundedSemaphore(2)
        self.install_state, self.cache = {}, OrderedDict()

    def location(self):
        return self.root / ('plantuml-'+LOCK['plantuml']['version']+'-'+platform_key()+'-'+hashlib.sha256(json.dumps(LOCK,sort_keys=True).encode()).hexdigest()[:8])

    def executables(self, directory=None):
        directory = directory or self.location()
        java = next(iter(directory.rglob('java.exe' if os.name == 'nt' else 'java')), None) if directory.exists() else None
        jar = directory / 'plantuml.jar'
        if not java or not jar.is_file():
            raise LookupError('标准 UML 本地运行时尚未安装')
        return java, jar

    def status(self):
        with self.lock:
            if self.install_state.get('status') in ('installing','failed'):
                return dict(self.install_state)
            try:
                self.executables()
                return dict(status='ready', version=LOCK['plantuml']['version'], platform=platform_key())
            except LookupError:
                supported = platform_key() in LOCK['java']
                return dict(status='missing' if supported else 'unsupported', version=LOCK['plantuml']['version'], platform=platform_key(),
                            message='' if supported else '当前平台暂无锁定的 Java 21 发行包：'+platform_key())

    def install(self):
        with self.lock:
            if self.install_state.get('status') == 'installing' or self.status()['status'] == 'ready':
                return self.status()
            if platform_key() not in LOCK['java']:
                raise ValueError('暂无此平台的锁定运行时发行包：'+platform_key())
            self.install_state = dict(status='installing', phase='准备下载', received=0, total=0)
            threading.Thread(target=self._install, daemon=True, name='uml-runtime-install').start()
            return dict(self.install_state)

    def _progress(self, phase, received=0, total=0):
        with self.lock:
            self.install_state.update(phase=phase, received=received, total=total)

    def _install(self):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.install-', dir=self.root) as name:
                stage = Path(name); payload = stage/'runtime'; payload.mkdir()
                package = LOCK['java'][platform_key()]
                archive = cached_download(package, self.root/'downloads', lambda a,b:self._progress('下载 Java 21',a,b))
                self._progress('校验并解压 Java')
                extract(archive, payload)
                plantuml = cached_download(LOCK['plantuml'], self.root/'downloads', lambda a,b:self._progress('下载 PlantUML',a,b))
                shutil.copyfile(plantuml, payload/'plantuml.jar')
                java, jar = self.executables(payload)
                probe = subprocess.run([str(java),'-Djava.awt.headless=true','-DPLANTUML_SECURITY_PROFILE=SANDBOX','-jar',str(jar),'-tsvg','-pipe','-nometadata'],
                    input='@startuml\n!pragma layout smetana\nclass Probe\n@enduml\n',text=True,capture_output=True,timeout=30)
                if probe.returncode or '<svg' not in probe.stdout:
                    raise ValueError('本地渲染探测失败：'+probe.stderr[-300:])
                (payload/'runtime.json').write_text(json.dumps(LOCK, indent=2))
                destination = self.location()
                # Never replace a working installation; publish the complete new
                # version under its content-addressed name in one rename.
                if not destination.exists():
                    payload.rename(destination)
            with self.lock:
                self.install_state = {}
        except Exception as exc:
            with self.lock:
                self.install_state = dict(status='failed', message=str(exc)[:500])

    def render(self, document):
        projection = serialize(document['model'])
        key = (document['id'], document['revision'], document['snapshotId'], VERSION, LOCK['plantuml']['version'])
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return dict(self.cache[key], cached=True)
        java, jar = self.executables()
        if not self.slots.acquire(timeout=1):
            raise ValueError('标准 UML 正在渲染其他图，请稍后重试')
        try:
            env = {k:v for k,v in os.environ.items() if k not in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH')}
            env['PLANTUML_SECURITY_PROFILE'] = 'SANDBOX'
            command = [str(java),'-Xmx256m','-Djava.awt.headless=true','-DPLANTUML_SECURITY_PROFILE=SANDBOX',
                       '-jar',str(jar),'-tsvg','-pipe','-nometadata','-charset','UTF-8']
            with tempfile.TemporaryDirectory(prefix='strata-uml-') as cwd:
                process = subprocess.run(command, input=projection['source'], capture_output=True, text=True, env=env, cwd=cwd, timeout=30)
            if process.returncode or '<svg' not in process.stdout:
                raise ValueError('标准 UML 渲染失败：'+process.stderr[-500:])
            svg = sanitize_svg(process.stdout, projection['elements'])
            result = dict(**projection, svg=svg, rendererVersion=LOCK['plantuml']['version'], revision=document['revision'], cached=False)
            with self.lock:
                self.cache[key] = result
                while len(self.cache)>32:
                    self.cache.popitem(last=False)
            return result
        except subprocess.TimeoutExpired as exc:
            raise ValueError('标准 UML 渲染超过 30 秒，请缩小图范围') from exc
        finally:
            self.slots.release()
