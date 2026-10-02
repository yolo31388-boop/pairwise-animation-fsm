"""
pairwise-animation-fsm - AnimationFSM

This module contains a deliberately broken implementation.
Fix all bugs so that tests pass.
"""


class AnimationFSM:
    def __init__(self):
        self.state = {}

    def transition_state(self, *args, **kwargs):
        """BUG: 状态切换不做过渡动画，直接硬切"""
        return None

    def update_state(self, *args, **kwargs):
        """BUG: 状态更新不做时间累积，动画播到一半切状态"""
        return None

    def calculate_blend_tree(self, *args, **kwargs):
        """BUG: 混合树只做简单插值，不做参数驱动"""
        return None

    def trigger_animation_event(self, *args, **kwargs):
        """BUG: 动画事件不做时机，开始和结束都触发同一个"""
        return None

    def update_animation_layer(self, *args, **kwargs):
        """BUG: 动画层不做遮罩，上半身动画影响下半身"""
        return None

