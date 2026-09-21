"""Empty on purpose: its presence makes pytest add this directory (the ament_python
package root, one level above the `swarm_coordination/` package itself) to `sys.path`,
so `test/*.py` can `import swarm_coordination.<module>` without a `pip install -e .`
step — CI runs `pytest` directly against a checkout, not an installed ROS workspace.
"""
