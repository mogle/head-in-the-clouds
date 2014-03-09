from headintheclouds.ensemble.container import Container
from headintheclouds.ensemble.server import Server

def build_thing_index(servers):
    thing_index = {}
    for server in servers.values():
        thing_index[server.thing_name()] = server
        for container in server.containers.values():
            thing_index[container.thing_name()] = container
    return thing_index

def refresh_thing_index(thing_index):
    # TODO this starting to get really ugly. need to refactor
    for thing_name, thing in thing_index.items():
        if isinstance(thing, Server):
            for container_name, container in thing.containers.items():
                thing.containers[container_name] = thing_index[container.thing_name()]
        elif isinstance(thing, Container):
            thing.host = thing_index[thing.host.thing_name()]
