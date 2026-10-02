"""
pairwise-animation-fsm - AnimationFSM

A game animation state machine:

- ``transition_state`` performs condition-checked, priority-aware state
  transitions with a cross-fade (transition) animation instead of hard cuts.
- ``update_state`` accumulates time, handles looping vs. clamped playback
  and fires keyframe events as their time is crossed.
- ``calculate_blend_tree`` evaluates a parameter-driven, multi-parameter
  blend tree with clamped parameters and normalized weights.
- ``trigger_animation_event`` emits timed, parameterized events through an
  ordered queue.
- ``update_animation_layer`` combines animation layers using bone masks,
  per-layer weights and explicit ordering.
"""


class AnimationFSM:
    def __init__(self, states=None, transitions=None, parameters=None,
                 layers=None, events=None, **kwargs):
        self.state = {}                 # name -> state definition
        self.current_state = None
        self.previous_state = None
        self.state_time = 0.0           # time accumulated in current state
        self.transition = None          # active cross-fade info or None
        self.transition_rules = []      # allowed transitions + conditions
        self.blend_parameters = {}      # name -> {"value", "min", "max"}
        self.events = []                # registered keyframe events
        self.event_queue = []           # pending events (time, seq ordered)
        self.layers = []                # animation layers
        self._event_seq = 0
        if states:
            for state in states:
                if isinstance(state, dict):
                    self.add_state(
                        state.get("name", state.get("state")),
                        animation=state.get("animation"),
                        duration=state.get("duration", state.get("length",
                                                    state.get("time", 1.0))),
                        loop=state.get("loop", state.get("is_looping",
                                          state.get("looping", False))),
                        priority=state.get("priority",
                                           state.get("state_priority", 0)),
                    )
                else:
                    self.add_state(state)
        if transitions:
            for rule in transitions:
                self.add_transition(
                    rule.get("source", rule.get("from")),
                    rule.get("target", rule.get("to")),
                    condition=rule.get("condition"),
                    priority=rule.get("priority", 0),
                    duration=rule.get("duration",
                                      rule.get("transition_time", 0.2)),
                )
        if parameters:
            for name, spec in parameters.items():
                if isinstance(spec, dict):
                    self.add_blend_parameter(
                        name, value=spec.get("value", spec.get("default",
                                                              0.0)),
                        min=spec.get("min", spec.get("minimum", 0.0)),
                        max=spec.get("max", spec.get("maximum", 1.0)),
                    )
                else:
                    self.add_blend_parameter(name, value=spec)
        if events:
            for event in events:
                self.add_event(event["state"],
                               event.get("name", event.get("event")),
                               event.get("time", event.get("frame")),
                               params=event.get("params", event.get("data")))
        if layers:
            self.update_animation_layer(layers=layers)

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    def add_state(self, name, animation=None, duration=1.0, loop=False,
                  priority=0):
        self.state[name] = {
            "name": name,
            "animation": animation if animation is not None else name,
            "duration": float(duration),
            "loop": bool(loop),
            "priority": priority,
            "finished": False,
        }
        if self.current_state is None:
            self.current_state = name
            self._enqueue_event("start", "start", {"state": name}, time=0.0)
        return self.state[name]

    def add_transition(self, source, target, condition=None, priority=0,
                       duration=0.2):
        rule = {
            "source": source,
            "target": target,
            "condition": condition,
            "priority": priority,
            "duration": float(duration),
        }
        self.transition_rules.append(rule)
        return rule

    def add_event(self, state, name, time, params=None):
        event = {
            "state": state,
            "name": name,
            "time": float(time),
            "params": dict(params) if params else {},
        }
        self.events.append(event)
        return event

    def add_blend_parameter(self, name, value=0.0, min=0.0, max=1.0):
        param = {"value": float(value), "min": float(min), "max": float(max)}
        param["value"] = self._clamp(param["value"], param["min"],
                                     param["max"])
        self.blend_parameters[name] = param
        return param

    def add_layer(self, name, animation=None, weight=1.0, mask=None, order=0):
        layer = {
            "name": name,
            "animation": animation,
            "weight": self._clamp(float(weight), 0.0, 1.0),
            "mask": set(mask) if mask else set(),
            "order": order,
        }
        self.layers.append(layer)
        return layer

    # ------------------------------------------------------------------
    # State transitions: cross-fade + conditions + priority
    # ------------------------------------------------------------------
    def transition_state(self, target=None, transition_time=None,
                         priority=None, force=False, context=None, **kwargs):
        if target is None:
            target = kwargs.get("new_state", kwargs.get(
                "to_state", kwargs.get("to", kwargs.get("state"))))
        if transition_time is None:
            transition_time = kwargs.get("duration", kwargs.get(
                "blend_time", kwargs.get("fade_time")))
        if priority is None:
            priority = kwargs.get("state_priority")
        if context is None:
            context = kwargs.get("params", kwargs.get("conditions"))
        if target is None:
            return {
                "changed": False,
                "current": self.current_state,
                "previous": self.previous_state,
                "transitioning": self.transition is not None,
                "transition": self.transition,
            }

        if target not in self.state:
            self.add_state(target)
        new_state = self.state[target]
        current = self.state.get(self.current_state)
        if priority is None:
            priority = new_state["priority"]

        # Conditions: once rules exist, a matching rule with a passing
        # condition is required - not every state may cut to every state.
        rule = self._find_rule(self.current_state, target)
        if self.transition_rules and rule is None:
            return self._rejected("no_matching_rule", target)
        if rule is not None and rule["condition"] is not None:
            if not self._eval_condition(rule["condition"], context):
                return self._rejected("condition_not_met", target)

        # Priority: a lower-priority request cannot interrupt a higher-
        # priority transition or a higher-priority non-looping animation.
        if not force:
            if (self.transition is not None
                    and self.transition["priority"] > priority):
                return self._rejected("lower_priority_than_transition",
                                      target)
            if (current is not None and not current["loop"]
                    and not current["finished"]
                    and current["priority"] > priority):
                return self._rejected("lower_priority_than_current", target)

        # Transition animation: cross-fade over ``duration`` instead of a
        # hard cut, so poses blend and no positional pop occurs.
        duration = transition_time
        if duration is None:
            duration = rule["duration"] if rule is not None else 0.2
        self.previous_state = self.current_state
        self.current_state = target
        self.state_time = 0.0
        new_state["finished"] = False
        self.transition = {
            "from": self.previous_state,
            "to": target,
            "elapsed": 0.0,
            "duration": max(0.0, float(duration)),
            "priority": priority,
        }
        self._enqueue_event("start", "start", {"state": target}, time=0.0)
        return {
            "changed": True,
            "from": self.previous_state,
            "to": target,
            "transition": self.transition,
        }

    # ------------------------------------------------------------------
    # State update: time accumulation + looping + keyframe events
    # ------------------------------------------------------------------
    def update_state(self, dt=0.0, **kwargs):
        if not dt:
            dt = kwargs.get("delta_time", kwargs.get(
                "delta", kwargs.get("elapsed", kwargs.get("time", 0.0))))
        dt = float(dt)
        previous_time = self.state_time
        self.state_time += dt

        # Advance the active cross-fade.
        if self.transition is not None:
            self.transition["elapsed"] += dt
            if self.transition["elapsed"] >= self.transition["duration"]:
                self.transition = None

        fired = []
        finished_now = False
        state = self.state.get(self.current_state)
        if state is not None:
            duration = state["duration"]
            if state["loop"] and duration > 0.0:
                # Looping clips wrap around instead of stopping.
                fired.extend(self._collect_events(
                    state, previous_time, min(self.state_time, duration)))
                self.state_time %= duration
            elif duration > 0.0 and self.state_time >= duration:
                # Non-looping clips clamp at the end and stop; the
                # character no longer pops back up after a death anim.
                fired.extend(self._collect_events(state, previous_time,
                                                  duration))
                self.state_time = duration
                if not state["finished"]:
                    state["finished"] = True
                    finished_now = True
                    self._enqueue_event("end", "end",
                                        {"state": self.current_state},
                                        time=duration)
            else:
                fired.extend(self._collect_events(state, previous_time,
                                                  self.state_time))

        return {
            "state": self.current_state,
            "time": self.state_time,
            "delta": dt,
            "finished": state["finished"] if state is not None else False,
            "finished_now": finished_now,
            "transitioning": self.transition is not None,
            "transition": self.transition,
            "events": fired,
        }

    # ------------------------------------------------------------------
    # Blend tree: parameter-driven, multi-parameter, normalized
    # ------------------------------------------------------------------
    def calculate_blend_tree(self, params=None, nodes=None, **kwargs):
        if params is None:
            params = kwargs.get("parameters", kwargs.get("param_values"))
        if nodes is None:
            nodes = kwargs.get("blend_nodes", kwargs.get(
                "animations", kwargs.get("tree")))
        if isinstance(nodes, dict):
            nodes = [dict(spec, animation=name) if isinstance(spec, dict)
                     else {"animation": name, "weight": spec}
                     for name, spec in nodes.items()]
        # Parameter-driven: update parameters, clamping out-of-range
        # values into [min, max] so bad input cannot scramble the blend.
        if params:
            for name, value in params.items():
                param = self.blend_parameters.setdefault(
                    name, {"value": 0.0, "min": 0.0, "max": 1.0})
                if isinstance(value, dict):
                    param.update(value)
                else:
                    param["value"] = value
                param["value"] = self._clamp(float(param["value"]),
                                             param["min"], param["max"])

        result = {
            "parameters": {name: p["value"]
                           for name, p in self.blend_parameters.items()},
            "weights": {},
        }

        # Multi-parameter blending: distance in normalized parameter
        # space decides each node's raw weight.
        if nodes:
            raw = {}
            for node in nodes:
                animation = node.get("animation", node.get("name"))
                if "weight" in node and "params" not in node:
                    raw[animation] = max(0.0, float(node["weight"]))
                    continue
                node_params = node.get("params", node.get("parameters", {}))
                squared = 0.0
                for pname, pvalue in node_params.items():
                    param = self.blend_parameters.get(pname)
                    current = param["value"] if param else 0.0
                    span = (param["max"] - param["min"]) if param else 1.0
                    if span <= 0.0:
                        span = 1.0
                    squared += ((current - pvalue) / span) ** 2
                raw[animation] = 1.0 / (squared ** 0.5 + 1e-6)
            # Normalization: weights always sum to 1.
            total = sum(raw.values())
            if total > 0.0:
                result["weights"] = {a: w / total for a, w in raw.items()}
        return result

    # ------------------------------------------------------------------
    # Animation events: timing + parameters + ordered queue
    # ------------------------------------------------------------------
    def trigger_animation_event(self, name=None, timing=None, params=None,
                                time=None, **kwargs):
        if name is None:
            name = kwargs.get("event", kwargs.get(
                "event_name", kwargs.get("type")))
        if timing is None:
            timing = kwargs.get("phase", kwargs.get("trigger_time"))
        if params is None:
            params = kwargs.get("data", kwargs.get("payload"))
        if time is None and "at" in kwargs:
            time = kwargs["at"]
        if name is None:
            # Drain the queue in order: scheduled time first, then
            # insertion sequence, so simultaneous events stay ordered.
            pending = sorted(self.event_queue,
                             key=lambda e: (e["time"], e["seq"]))
            self.event_queue.clear()
            return {"events": pending, "count": len(pending)}
        return self._enqueue_event(
            name, timing if timing is not None else "manual", params,
            time=self.state_time if time is None else float(time))

    # ------------------------------------------------------------------
    # Animation layers: bone masks + weights + ordering
    # ------------------------------------------------------------------
    def update_animation_layer(self, layers=None, dt=0.0, **kwargs):
        if layers is None:
            layers = kwargs.get("animation_layers", kwargs.get("layer_list"))
        if layers:
            self.layers = []
            for index, layer in enumerate(layers):
                self.add_layer(
                    layer.get("name", "layer_%d" % index),
                    animation=layer.get("animation"),
                    weight=layer.get("weight", 1.0),
                    mask=layer.get("mask", layer.get("bones",
                                      layer.get("bone_mask"))),
                    order=layer.get("order", layer.get("priority", index)),
                )

        # Ordering: low order is the base layer; higher-order layers are
        # applied afterwards and override lower ones per bone.
        ordered = sorted(self.layers, key=lambda l: l["order"])
        bones = {}
        for layer in ordered:
            if layer["weight"] <= 0.0:
                continue
            # Mask: a layer only drives the bones in its mask (empty mask
            # means full body), so an upper-body layer never touches legs.
            affected = layer["mask"] if layer["mask"] else {"*"}
            for bone in affected:
                bones[bone] = {
                    "layer": layer["name"],
                    "animation": layer["animation"],
                    "weight": layer["weight"],
                }
        return {
            "layers": [
                {"name": l["name"], "order": l["order"],
                 "weight": l["weight"], "mask": sorted(l["mask"])}
                for l in ordered
            ],
            "bones": bones,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp(value, low, high):
        return max(low, min(high, value))

    def _rejected(self, reason, target):
        return {
            "changed": False,
            "reason": reason,
            "current": self.current_state,
            "target": target,
        }

    def _find_rule(self, source, target):
        matches = [
            r for r in self.transition_rules
            if r["target"] == target
            and (r["source"] in (source, None, "*"))
        ]
        if not matches:
            return None
        return max(matches, key=lambda r: r["priority"])

    @staticmethod
    def _eval_condition(condition, context):
        if callable(condition):
            try:
                return bool(condition(context))
            except TypeError:
                return bool(condition())
        if isinstance(condition, str):
            return bool((context or {}).get(condition))
        return bool(condition)

    def _enqueue_event(self, name, timing, params, time):
        event = {
            "name": name,
            "animation": self.current_state,
            "timing": timing,
            "params": dict(params) if params else {},
            "time": float(time),
            "seq": self._event_seq,
        }
        self._event_seq += 1
        self.event_queue.append(event)
        return event

    def _collect_events(self, state, start, end):
        fired = []
        due = [e for e in self.events
               if e["state"] == state["name"] and start < e["time"] <= end]
        for event in sorted(due, key=lambda e: e["time"]):
            fired.append(self._enqueue_event(
                event["name"], "keyframe", event["params"],
                time=event["time"]))
        return fired
