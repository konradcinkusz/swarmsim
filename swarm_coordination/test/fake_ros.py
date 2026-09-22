"""A minimal stand-in for rclpy and the message packages the nodes import.

It exists so the node adapters in swarm_coordination/nodes/ can be exercised by pytest
without a ROS 2 install: CI imports only rclpy-free code, so without this nothing but
the SITL smoke would ever run a node. It mirrors only the API surface the nodes use —
topic names resolve against the node's namespace as rclpy resolves them, messages carry
the fields the real ones do, and a node keeps its publishers, timers, clock and logger in
the attributes rclpy keeps them in — and it is not a simulation of DDS: delivery is
immediate, and QoS is recorded, not enforced.
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
    def __init__(self, srv_name):
        self.srv_name = srv_name
        self.requests = []
        self.ready = True
        self.response = SimpleNamespace(mode_sent=True, success=True, result=0)

    def service_is_ready(self):
        return self.ready

    def call_async(self, request):
        self.requests.append(request)
        return _Future(self.response)


class _Timer:
    def __init__(self, period_s, callback):
        self.timer_period_ns = int(period_s * 1e9)
        self.callback = callback


class _Parameter:
    def __init__(self, value):
        self.value = value


# What rclpy's own Node.__init__ sets on the node itself (rclpy, humble branch,
# rclpy/node.py). rclpy lets a subclass overwrite any of them, and the node breaks later,
# somewhere else. The mission dispatcher kept its publishers in a dict named
# `self._publishers`; every create_publisher after that failed with "'dict' object has no
# attribute 'append'", so it died at start in every SITL smoke run that started it, while
# these tests, whose fake kept its books under other names, passed. The fake keeps its
# books under rclpy's names and refuses a subclass that assigns one of them.
RCLPY_NODE_ATTRIBUTES = frozenset(
    {
        "_context",
        "_parameters",
        "_publishers",
        "_subscriptions",
        "_clients",
        "_services",
        "_timers",
        "_guards",
        "_default_callback_group",
        "_parameters_callbacks",
        "_rate_group",
        "_allow_undeclared_parameters",
        "_parameter_overrides",
        "_descriptors",
        "_logger",
        "_parameter_event_publisher",
        "_clock",
        "_time_source",
        "_parameter_service",
    }
)


class Node:
    def __init__(self, name):
        # rclpy's own bookkeeping, under rclpy's names (RCLPY_NODE_ATTRIBUTES).
        self._context = None
        self._parameters = {}
        self._publishers = []
        self._subscriptions = []
        self._clients = []
        self._services = []
        self._timers = []
        self._guards = []
        self._default_callback_group = None
        self._parameters_callbacks = []
        self._rate_group = None
        self._allow_undeclared_parameters = False
        self._parameter_overrides = dict(getattr(BUS, "parameter_overrides", {}))
        self._descriptors = {}
        self._logger = _Logger()
        self._parameter_event_publisher = None
        self._clock = _Clock()
        self._time_source = None
        self._parameter_service = None
        # The fake's own state, name-mangled so that no subclass can collide with it.
        self.__name = name
        self.__namespace = BUS.namespace
        BUS.nodes.append(self)

    def __setattr__(self, name, value):
        if name in RCLPY_NODE_ATTRIBUTES and name in self.__dict__:
            raise AttributeError(
                f"{type(self).__name__} assigns self.{name}, where rclpy.node.Node keeps its "
                "own state; in rclpy the node breaks later, somewhere else "
                "(fake_ros.RCLPY_NODE_ATTRIBUTES)"
            )
        object.__setattr__(self, name, value)

    # rclpy's read-only views of what the node has created.
    @property
    def publishers(self):
        yield from self._publishers

    @property
    def subscriptions(self):
        yield from self._subscriptions

    @property
    def clients(self):
        yield from self._clients

    @property
    def timers(self):
        yield from self._timers

    def get_name(self):
        return self.__name

    def get_namespace(self):
        return self.__namespace

    def declare_parameter(self, name, value=None):
        self._parameters[name] = _Parameter(self._parameter_overrides.get(name, value))
        return self._parameters[name]

    def get_parameter(self, name):
        return self._parameters[name]

    def create_publisher(self, msg_type, topic, qos):
        publisher = _Publisher(BUS.resolve(self.__namespace, topic), qos)
        self._publishers.append(publisher)
        BUS.publishers.append(publisher.topic)
        return publisher

    def create_subscription(self, msg_type, topic, callback, qos):
        subscription = _Subscription(BUS.resolve(self.__namespace, topic), callback)
        self._subscriptions.append(subscription)
        BUS.subscribers[subscription.topic].append(callback)
        return subscription

    def destroy_subscription(self, subscription):
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)
            BUS.subscribers[subscription.topic].remove(subscription.callback)
            return True
        return False

    def create_client(self, srv_type, srv_name):
        client = _Client(BUS.resolve(self.__namespace, srv_name))
        self._clients.append(client)
        return client

    def create_timer(self, timer_period_sec, callback):
        timer = _Timer(timer_period_sec, callback)
        self._timers.append(timer)
        return timer

    def get_clock(self):
        return self._clock

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
    """Runs a node's timers once (only those with ``period``, in seconds, when given)."""
    for timer in list(node.timers):
        if period is None or abs(timer.timer_period_ns - period * 1e9) < 1:
            timer.callback()


def client(node, service: str):
    """The node's client for ``service`` (the resolved name), to read what it was asked."""
    return next(c for c in node.clients if c.srv_name == service)
