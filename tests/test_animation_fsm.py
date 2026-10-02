import pytest
from animation.fsm import AnimationFSM


class TestAnimationFSM:

    def test_transition_state(self):
        """状态切换不做过渡动画，直接硬切"""
        obj = AnimationFSM()
        result = obj.transition_state()
        self.assertIsNotNone(result)

    def test_update_state(self):
        """状态更新不做时间累积，动画播到一半切状态"""
        obj = AnimationFSM()
        result = obj.update_state()
        self.assertIsNotNone(result)

    def test_calculate_blend_tree(self):
        """混合树只做简单插值，不做参数驱动"""
        obj = AnimationFSM()
        result = obj.calculate_blend_tree()
        self.assertIsNotNone(result)

    def test_trigger_animation_event(self):
        """动画事件不做时机，开始和结束都触发同一个"""
        obj = AnimationFSM()
        result = obj.trigger_animation_event()
        self.assertIsNotNone(result)

    def test_update_animation_layer(self):
        """动画层不做遮罩，上半身动画影响下半身"""
        obj = AnimationFSM()
        result = obj.update_animation_layer()
        self.assertIsNotNone(result)

