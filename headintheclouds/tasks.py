import sys
from functools import wraps
import collections
import yaml
from StringIO import StringIO
from collections import defaultdict
import uuid
import mimetypes
import urlparse
import docker

from fabric.api import parallel, env, sudo, settings, local, runs_once, run, abort, put
import fabric.api
import fabric.contrib.project as project

import util

def task(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with _provider_settings():
            env.role = env.all_nodes[env.host]['role']
            func(*args, **kwargs)
    return fabric.api.task(wrapper)

def once_per_provider(func_name, *args, **kwargs):
    def wrapped():
        for p in env.providers:
            provider = sys.modules[p]
            print '\n%s:\n' % provider.provider_name.upper()
            getattr(provider, func_name)(*args, **kwargs)
    wrapped.__name__ = func_name
    setattr(sys.modules[__name__], func_name, runs_once(fabric.api.task(wrapped)))

once_per_provider('pricing')
once_per_provider('nodes')

@task
@parallel
def terminate():
    _provider().terminate()

@task
@parallel
def rename(role):
    _provider().rename(role)

@task
def uncache():
    util.cache().flush()

@task
def ssh(cmd=''):
    local('ssh -o StrictHostKeyChecking=no -i "%s" %s@%s "%s"' % (
        env.key_filename, env.user, env.host, cmd))

@task
def mosh():
    local('mosh --ssh="ssh -o StrictHostKeyChecking=no -i \"%s\"" %s@%s' % (
        env.key_filename, env.user, env.host))

@task
@parallel
def puppet(init, puppet_dir='puppet', update=True):
    if str(update) == 'True':
        sudo('dpkg --configure -a')
        sudo('apt-get update')

        sudo('apt-get -y install puppet')
        sudo('chmod 777 /opt')

    if not puppet_dir.endswith('/'):
        puppet_dir += '/'
    remote_puppet_dir = '/etc/puppet'
    sudo('chown -R %s %s' % (env.user, remote_puppet_dir))

    nodes_yaml = yaml.safe_dump(_get_environment(True))
    put(StringIO(nodes_yaml), remote_puppet_dir + '/nodes.yaml')
    
    project.rsync_project(local_dir=puppet_dir, remote_dir=remote_puppet_dir,
                          ssh_opts='-o StrictHostKeyChecking=no')
    sudo('FACTER_CLOUD="%s" puppet apply %s/%s' % (_provider().provider_name, remote_puppet_dir, init))

#@task
#@parallel
#def docker(image, options=None):
#    ret = run('which docker')
#    if ret.failed:
#        docker_setup()
#    sudo('docker run %s %s' % (options, image))

@task
@parallel
def docker_setup():
    sudo('sh -c "wget -qO- https://get.docker.io/gpg | apt-key add -"')
    sudo('sudo sh -c "echo deb http://get.docker.io/ubuntu docker main > /etc/apt/sources.list.d/docker.list"')
    sudo('apt-get update')
    sudo('apt-get -y install linux-image-extra-virtual')
    sudo('apt-get -y install lxc-docker')
    sudo('apt-get -y install mosh')
    sudo('reboot')

@task
#@parallel
def docker_run(image, cmd=None, name=None, ports=None):
    parts = ['docker', 'run', '-d']
    if name:
        parts += ['-name', name]
    parts += [image]
    if cmd:
        parts += [cmd]
    result = sudo(' '.join(parts))
    process = result.strip()

    if ports:
        ports = ports.split(',')
        for port in ports:
            port = port.strip()
            docker.bind(process, port)

    #iptables -t nat -A DOCKER -p tcp --dport 80 -j DNAT --to-destination 172.17.0.250:80
    #iptables -t nat -D DOCKER -p tcp --dport 80 -j DNAT --to-destination 172.17.0.250:80 # to disconnect
'''
    function docker-get-ip() {
        container=$1
        docker inspect $container | grep IPAddress | sed -r 's/^.+: "(.+)",/\1/g'
    }

    function docker-bind() {
        container=$1
        port=$2
        docker-unbind $port
        ip=$(docker-get-ip $container)
        iptables -t nat -A DOCKER -p tcp --dport $port -j DNAT --to-destination $ip:$port
    }

    function docker-unbind() {
        port=$1
        iptables -t nat -S | grep "^-A DOCKER -p tcp -m tcp --dport $port" |
        while read rule
        do
            undo_rule=$(echo $rule | sed 's/^-A DOCKER/-D DOCKER/')
            iptables -t nat $undo_rule
        done
    }
'''

@task
@runs_once
def tunnel(local_port, remote_port=None):
    if remote_port is None:
        remote_port = local_port
    local('ssh -o StrictHostKeyChecking=no -i "%(key)s" -f %(user)s@%(host)s -L %(local_port)s:localhost:%(remote_port)s -N' % {
        'key': env.key_filename,
        'user': env.user,
        'host': env.host,
        'local_port': local_port,
        'remote_port': remote_port
    })


@task
@parallel
def ping():
    local('ping -c1 %s' % env.host)

def _get_environment(running_only=False):
    environment = defaultdict(list)
    for p in env.providers:
        if p == env.all_nodes[env.host]['provider']:
            provider_env = sys.modules[p].get_local_environment(running_only)
        else:
            provider_env = sys.modules[p].get_remote_environment(running_only)
        for role, nodes in provider_env.iteritems():
            environment[role].extend(nodes)
    return dict(environment)

def _provider():
    if env.host not in env.all_nodes:
        abort('No such host found')
    return sys.modules[env.all_nodes[env.host]['provider']]

def _provider_settings():
    provider_env = _provider().settings
    return settings(**provider_env)

env.disable_known_hosts = True

def setup():
    if not hasattr(env, 'all_nodes'):
        env.all_nodes = {}
    if not hasattr(env, 'providers'):
        env.providers = {}

    env.roledefs = collections.defaultdict(list)
    for node in env.all_nodes.itervalues():
        role = node['role']
        env.roledefs[role].append(node['ip_address'])

    if not env.hosts:
        if env.roles:
            env.hosts = [i for r in env.roles for i in env.roledefs[r]]
        else:
            env.hosts = [x['ip_address'] for x in env.all_nodes.values()]

setup()
