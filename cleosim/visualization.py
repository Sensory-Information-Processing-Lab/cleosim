"""Tools for visualizing models and simulations"""
from __future__ import annotations
from typing import Tuple, Any, Union
from collections.abc import Iterable
from matplotlib.artist import Artist

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as anim
from mpl_toolkits.mplot3d import Axes3D
from brian2 import mm, Unit, NeuronGroup, ms, NetworkOperation, Quantity, SpikeMonitor

from cleosim.base import CLSimulator, InterfaceDevice

_neuron_alpha = 0.2


class VideoVisualizer(InterfaceDevice):
    """Device for visualizing a simulation.

    Must be injected after all other devices and before the simulation
    is run."""

    def __init__(
        self,
        devices_to_plot: list[InterfaceDevice] = "all",
        dt: Quantity = 1 * ms,
    ) -> None:
        """
        Parameters
        ----------
        devices_to_plot : list[InterfaceDevice], optional
            list of devices to include in the plot, just as in the :func:`plot`
            function, by default "all", which will include all recorders and
            stimulators currently injected when this visualizer is injected into
            the simulator
        dt : Brian 2 temporal Quantity, optional
            length of each frame---that is, every `dt` the visualizer takes a
            snapshot of the network, by default 1*ms
        """
        super().__init__("video_visualizer")
        self.neuron_groups = []
        self._spike_mons = []
        self._num_old_spikes = []
        self.devices_to_plot = devices_to_plot
        self.dt = dt
        # store data to generate video
        self._value_per_device_per_frame = []
        self._i_spikes_per_ng_per_frame: list[list[np.ndarray]] = []

    def init_for_simulator(self, simulator: CLSimulator):
        if self.devices_to_plot == "all":
            self.devices_to_plot = list(self.sim.recorders.values())
            self.devices_to_plot.extend(list(self.sim.stimulators.values()))
        # network op
        def snapshot(t):
            i_spikes_per_ng = [
                self._new_spikes_for_ng(i_ng) for i_ng in range(len(self.neuron_groups))
            ]
            self._i_spikes_per_ng_per_frame.append(i_spikes_per_ng)
            device_values = []
            for device in self.devices_to_plot:
                try:
                    device_values.append(device.value)
                # not all devices (recorders!) have a value or any changing state to plot
                except AttributeError:
                    device_values.append(None)
            self._value_per_device_per_frame.append(device_values)

        simulator.network.add(NetworkOperation(snapshot, dt=self.dt))

    def connect_to_neuron_group(self, neuron_group: NeuronGroup, **kwparams) -> None:
        self.neuron_groups.append(neuron_group)
        mon = SpikeMonitor(neuron_group)
        self._spike_mons.append(mon)
        self.brian_objects.add(mon)
        self._num_old_spikes.append(0)

    def generate_Animation(
        self, plotargs: dict, slowdown_factor: float = 10, **figargs: Any
    ) -> anim.Animation:
        """Create a matplotlib Animation object from the recorded simulation

        Parameters
        ----------
        plotargs : dict
            dictionary of arguments as taken by :func:`plot`. can include
            `xlim`, `ylim`, `zlim`, `colors`, `axis_scale_unit`, `invert_z`,
            and/or `scatterargs`. neuron groups and devices are
            automatically added and **figargs are specified separately.
        slowdown_factor : float, optional
            how much slower the animation will be rendered, as a multiple of
            real-time, by default 10
        **figargs : Any, optional
            keyword arguments passed to plt.figure(), such as figsize

        Returns
        -------
        :class:`matplotlib.animation.Animation`
            An Animation object capturing the desired visualization.
            See matplotlib's docs for saving and rendering options.
        """
        interval_ms = self.dt / ms * slowdown_factor
        self.fig = plt.figure(**figargs)
        self.ax = self.fig.add_subplot(111, projection="3d")
        neuron_artists, device_artists = _plot(
            self.ax,
            self.neuron_groups,
            devices_to_plot=self.devices_to_plot,
            **plotargs,
        )

        def update(i):
            device_values = self._value_per_device_per_frame[i]
            updated_artists = []
            for device, artists, value in zip(
                self.devices_to_plot, device_artists, device_values
            ):
                updated_artists_for_device = device.update_artists(artists, value)
                updated_artists.extend(updated_artists_for_device)
            self._update_neuron_artists_for_frame(neuron_artists, i)
            return updated_artists + neuron_artists

        return anim.FuncAnimation(
            self.fig,
            update,
            range(len(self._value_per_device_per_frame)),
            interval=interval_ms,
            blit=True,
        )

    def _update_neuron_artists_for_frame(self, artists, i_frame):
        i_spikes_per_ng = self._i_spikes_per_ng_per_frame[i_frame]
        # loop over neuron groups/artists
        for i_spikes, ng, artist in zip(i_spikes_per_ng, self.neuron_groups, artists):
            spike_counts = self._spikes_i_to_count_for_ng(i_spikes, ng)
            artist.set_alpha(None)  # remove alpha defined at collection level
            rgba = artist.get_edgecolor()
            alpha = np.zeros(ng.N)
            alpha[spike_counts == 0] = _neuron_alpha
            alpha[spike_counts > 0] = 1
            rgba[:, 3] = alpha
            # warning: this doesn't work. gets order wrong: artist.set_alpha(alpha)
            artist.set_color(rgba)

    def _spikes_i_to_count_for_ng(self, i_spikes, ng):
        counts = np.zeros(ng.N)
        counts[i_spikes] = 1
        return counts

    def _new_spikes_for_ng(self, i_ng):
        mon = self._spike_mons[i_ng]
        num_old = self._num_old_spikes[i_ng]
        new_i_spikes = mon.i[num_old:]
        self._num_old_spikes[i_ng] = len(mon.i)
        return new_i_spikes


def _plot(
    ax: Axes3D,
    neuron_groups: NeuronGroup,
    xlim: Tuple[float, float] = None,
    ylim: Tuple[float, float] = None,
    zlim: Tuple[float, float] = None,
    colors: Iterable = None,
    axis_scale_unit: Unit = mm,
    devices_to_plot: Iterable[InterfaceDevice] = [],
    invert_z: bool = True,
    scatterargs: dict = {},
) -> tuple[list[Artist], list[Artist]]:
    for ng in neuron_groups:
        for dim in ["x", "y", "z"]:
            if not hasattr(ng, dim):
                raise ValueError(f"{ng.name} does not have dimension {dim} defined.")

    assert colors is None or len(colors) == len(neuron_groups)
    neuron_artists = []
    for i in range(len(neuron_groups)):
        ng = neuron_groups[i]
        args = [ng.x / axis_scale_unit, ng.y / axis_scale_unit, ng.z / axis_scale_unit]
        kwargs = {"label": ng.name, "alpha": _neuron_alpha}
        if colors is not None:
            kwargs["color"] = colors[i]
        kwargs.update(scatterargs)
        neuron_artists.append(ax.scatter(*args, **kwargs))
        ax.set_xlabel(f"x ({axis_scale_unit._dispname})")
        ax.set_ylabel(f"y ({axis_scale_unit._dispname})")
        ax.set_zlabel(f"z ({axis_scale_unit._dispname})")

    xlim = ax.get_xlim() if xlim is None else xlim
    ylim = ax.get_ylim() if ylim is None else ylim
    zlim = ax.get_zlim() if zlim is None else zlim

    ax.set(xlim=xlim, ylim=ylim, zlim=zlim)
    z_aspect = zlim[0] - zlim[1] if invert_z else zlim[1] - zlim[0]
    ax.set_box_aspect((xlim[1] - xlim[0], ylim[1] - ylim[0], z_aspect))

    ax.legend()

    device_artists = []
    for device in devices_to_plot:
        device_artists.append(device.add_self_to_plot(ax, axis_scale_unit))

    return neuron_artists, device_artists


def plot(
    *neuron_groups: NeuronGroup,
    xlim: Tuple[float, float] = None,
    ylim: Tuple[float, float] = None,
    zlim: Tuple[float, float] = None,
    colors: Iterable = None,
    axis_scale_unit: Unit = mm,
    devices_to_plot: Iterable[InterfaceDevice] = [],
    invert_z: bool = True,
    scatterargs: dict = {},
    **figargs: Any,
) -> None:
    """Visualize neurons and interface devices

    Parameters
    ----------
    xlim : Tuple[float, float], optional
        xlim for plot, determined automatically by default
    ylim : Tuple[float, float], optional
        ylim for plot, determined automatically by default
    zlim : Tuple[float, float], optional
        zlim for plot, determined automatically by default
    colors : Iterable, optional
        colors, one for each neuron group, automatically determined by default
    axis_scale_unit : Unit, optional
        Brian unit to scale lim params, by default mm
    devices_to_plot : Iterable[InterfaceDevice], optional
        devices to add to the plot; add_self_to_plot is called
        for each. By default []
    invert_z : bool, optional
        whether to invert z-axis, by default True to reflect the convention
        that +z represents depth from cortex surface
    scatterargs : dict, optional
        arguments passed to plt.scatter() for each neuron group, such as marker
    **figargs : Any, optional
        keyword arguments passed to plt.figure(), such as figsize

    Raises
    ------
    ValueError
        When neuron group doesn't have x, y, and z already defined
    """
    fig = plt.figure(**figargs)
    ax = fig.add_subplot(111, projection="3d")
    _plot(
        ax,
        neuron_groups,
        xlim,
        ylim,
        zlim,
        colors,
        axis_scale_unit,
        devices_to_plot,
        invert_z,
        scatterargs,
    )
