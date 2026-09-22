"""A minimal stand-in for rclpy and the message packages the nodes import.

It exists so the node adapters in swarm_coordination/nodes/ can be exercised by pytest
without a ROS 2 install: CI imports only rclpy-free code, so without this nothing but
the SITL smoke would ever run a node. It mirrors only the API surface the nodes use —
topic names resolve against the node's namespace as rclpy resolves them, messages carry
the fields the real ones do — and it is not a simulation of DDS: delivery is immediate,
and QoS is recorded, not enforced.
"""

from __future__ import annotations

import sys
import types
from collections import defaultdict
from types import SimpleNamespace


class Bus:
    def __init__(self):
        self.subscribers = defaultdict(list)
        self.published = defaultdict(list)
        self.publishers = []  # topics, in the order their publishers were created
        self.time_ns = 0
        self.namespace = "/"
        self.nodes = []

    def resolve(self, namespace: str, topic: str) -> str:
        if topic.startswith("/"):
            return topic
        base = namespace.rstrip("/")
        return f"{base}/{topic}" if base else f"/{topic}"

    def publish(self, topic: str, msg) -> None:
        self.published[topic].append(msg)
        for callback in list(self.subscribers[topic]):
            callback(msg)

    def messages(self, topic: str) -> list:
        return self.published.get(topic, [])

    def advance(self, seconds: float) -> None:
        self.time_ns += int(seconds * 1e9)


BUS = Bus()


# --- rclpy ----------------------------------------------------------------------------


class _Time:
    def __init__(self, ns):
        self.nanoseconds = ns

    def to_msg(self):
        return SimpleNamespace(sec=self.nanoseconds // 10**9, nanosec=self.nanoseconds % 10**9)


class _Clock:
    def now(self):
        return _Time(BUS.time_ns)


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, text):
        self.lines.append(("info", text))

    def warning(self, text):
        self.lines.append(("warning", text))

    def error(self, text):
        self.lines.append(("error", text))


class _Publisher:
    def __init__(self, topic, qos):
        self.topic = topic
        self.qos = qos

    def publish(self, msg):
        BUS.publish(self.topic, msg)


class _Subscription:
    def __init__(self, topic, callback):
        self.topic = topic
        self.callback = callback


class _Future:
    """An already-answered call: callbacks run as soon as they are added."""

    def __init__(self, response):
        self._response = response

    def done(self):
        return True

    def result(self):
        return self._response

    def add_done_callback(self, callback):
        callback(self)


class _Client:
    def __init__(self, name):
        self.name = name
        self.requests = []
        self.ready = True
        self.response = SimpleNamespace(mode_sent=True, success=True, result=0)

    def service_is_ready(self):
        return self.ready

    def call_async(self, request):
        self.requests.append(request)
        return _Future(self.response)


class _Parameter:
    def __init__(self, value):
        self.value = value


class Node:
    def __init__(self, name):
        self._name = name
        self._namespace = BUS.namespace
        self._parameters = {}
        self._overrides = getattr(BUS, "parameter_overrides", {})
        self.subscriptions = []
        self.clients = {}
        self.timers = []
        self._logger = _Logger()
        BUS.nodes.append(self)

    def get_namespace(self):
        return self._namespace

    def declare_parameter(self, name, default):
        self._parameters[name] = self._overrides.get(name, default)

    def get_parameter(self, name):
        return _Parameter(self._parameters[name])

    def create_publisher(self, msg_type, topic, qos):
        publisher = _Publisher(BUS.resolve(self._namespace, topic), qos)
        BUS.publishers.append(publisher.topic)
        return publisher

    def create_subscription(self, msg_type, topic, callback, qos):
        subscription = _Subscription(BUS.resolve(self._namespace, topic), callback)
        BUS.subscribers[subscription.topic].append(callback)
        self.subscriptions.append(subscription)
        return subscription

    def destroy_subscription(self, subscription):
        BUS.subscribers[subscription.topic].remove(subscription.callback)
        self.subscriptions.remove(subscription)

    def create_client(self, srv_type, name):
        client = _Client(BUS.resolve(self._namespace, name))
        self.clients[client.name] = client
        return client

    def create_timer(self, period, callback):
        self.timers.append((period, callback))

    def get_clock(self):
        return _Clock()

    def get_logger(self):
        return self._logger

    def destroy_node(self):
        pass


class DurabilityPolicy:
    TRANSIENT_LOCAL = "transient_local"
    VOLATILE = "volatile"


class ReliabilityPolicy:
    RELIABLE = "reliable"
    BEST_EFFORT = "best_effort"


class QoSProfile:
    def __init__(self, depth, durability=None, reliability=None):
        self.depth = depth
        self.durability = durability
        self.reliability = reliability


# --- messages ---------------------------------------------------------------------------


class String:
    def __init__(self, data=""):
        self.data = data


class PoseStamped:
    def __init__(self):
        self.header = SimpleNamespace(stamp=None, frame_id="")
        self.pose = SimpleNamespace(
            position=SimpleNamespace(x=0.0, y=0.0, z=0.0),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=0.0),
        )


class State:
    def __init__(self, armed=False, mode=""):
        self.armed = armed
        self.mode = mode
        self.connected = True


class HomePosition:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.header = SimpleNamespace(stamp=None, frame_id="")
        self.position = SimpleNamespace(x=x, y=y, z=z)


class BatteryState:
    def __init__(self, percentage=float("nan")):
        self.percentage = percentage


class _Request:
    pass


class SetMode:
    class Request(_Request):
        def __init__(self):
            self.base_mode = 0
            self.custom_mode = ""


class CommandBool:
    class Request(_Request):
        def __init__(self):
            self.value = False


def install() -> Bus:
    """Registers the fake modules in sys.modules and returns a fresh bus."""
    global BUS
    BUS = Bus()

    def module(name, **attributes):
        mod = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    rclpy = module(
        "rclpy", init=lambda *a, **k: None, spin=lambda *a, **k: None, shutdown=lambda: None
    )
    rclpy.node = module("rclpy.node", Node=Node)
    rclpy.qos = module(
        "rclpy.qos",
        QoSProfile=QoSProfile,
        DurabilityPolicy=DurabilityPolicy,
        ReliabilityPolicy=ReliabilityPolicy,
        qos_profile_sensor_data=QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT),
    )
    module("std_msgs"), module("std_msgs.msg", String=String)
    module("geometry_msgs"), module("geometry_msgs.msg", PoseStamped=PoseStamped)
    module("mavros_msgs"), module("mavros_msgs.msg", State=State, HomePosition=HomePosition)
    module("mavros_msgs.srv", SetMode=SetMode, CommandBool=CommandBool)
    module("sensor_msgs"), module("sensor_msgs.msg", BatteryState=BatteryState)
    for name in list(sys.modules):
        if name.startswith("swarm_coordination.nodes."):
            del sys.modules[name]
    return BUS


def pose(x, y, z) -> PoseStamped:
    msg = PoseStamped()
    msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = x, y, z
    return msg


def fire(node, period=None) -> None:
    """Runs a node's timers once (only those with ``period`` when given)."""
    for timer_period, callback in node.timers:
        if period is None or abs(timer_period - period) < 1e-9:
            callback()
