"""Contains Probe and Signal classes and electrode coordinate functions"""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterable
from operator import concat
from typing import Any, Tuple

import numpy as np
from mpl_toolkits.mplot3d.axes3d import Axes3D
from brian2 import NeuronGroup, mm, Unit, Quantity, umeter

from cleosim.base import Recorder
from cleosim.utilities import get_orth_vectors_for_v


class Signal(ABC):
    """Base class representing something an electrode can record"""

    name: str
    brian_objects: set
    probe: Probe

    def __init__(self, name: str) -> None:
        """Base class representing something an electrode can record

        Constructor must be called at beginning of children constructors.

        Parameters
        ----------
        name : str
            Unique identifier used when reading the state from the network
        """
        self.name = name
        self.brian_objects = set()
        self.probe = None

    def init_for_probe(self, probe: Probe) -> None:
        """Called when attached to a probe.

        Ensures signal can access probe and is only attached
        to one

        Parameters
        ----------
        probe : Probe
            Probe to attach to

        Raises
        ------
        ValueError
            When signal already attached to another probe
        """
        if self.probe is not None and self.probe is not probe:
            raise ValueError(
                f"Signal {self.name} has already been initialized "
                f"for Probe {self.probe.name} "
                f"and cannot be used with another."
            )
        self.probe = probe

    @abstractmethod
    def connect_to_neuron_group(self, neuron_group: NeuronGroup, **kwparams):
        pass

    @abstractmethod
    def get_state(self) -> Any:
        pass

    def reset(self, **kwargs) -> None:
        """Reset signal to a neutral state"""
        pass


class Probe(Recorder):
    """Picks up specified signals across an array of electrodes"""

    coords: Quantity
    signals: list[Signal]
    n: int

    def __init__(
        self, name: str, coords: Quantity, signals: Iterable[Signal] = []
    ) -> None:
        """Picks up specified signals across an array of electrodes

        Parameters
        ----------
        name : str
            Unique identifier for device
        coords : Quantity
            Coordinates of n electrodes. Must be an n x 3 array (with unit)
            where columns represent x, y, and z
        signals : Iterable[Signal], optional
            Signals to record with probe, by default [].
            Can be specified later with :meth:`add_signals`.

        Raises
        ------
        ValueError
            When coords aren't n x 3
        """
        super().__init__(name)
        self.coords = coords.reshape((-1, 3))
        if len(self.coords.shape) != 2 or self.coords.shape[1] != 3:
            raise ValueError(
                "coords must be an n by 3 array (with unit) with x, y, and z"
                "coordinates for n contact locations."
            )
        self.n = len(self.coords)
        self.signals = []
        self.add_signals(*signals)

    def add_signals(self, *signals: Signal) -> None:
        """Add signals to the probe for recording

        Parameters
        ----------
        *signals : Signal
            signals to add
        """
        for signal in signals:
            signal.init_for_probe(self)
            self.signals.append(signal)

    def connect_to_neuron_group(
        self, neuron_group: NeuronGroup, **kwparams: Any
    ) -> None:
        """Configure probe to record from given neuron group

        Will call :meth:`Signal.connect_to_neuron_group` for each signal

        Parameters
        ----------
        neuron_group : NeuronGroup
            neuron group to connect to, i.e., record from
        **kwparams : Any
            Passed in to signals' connect functions, needed for some signals
        """
        for signal in self.signals:
            signal.connect_to_neuron_group(neuron_group, **kwparams)
            self.brian_objects.update(signal.brian_objects)

    def get_state(self) -> dict:
        """Get current state from probe, i.e., all signals

        Returns
        -------
        dict
            {'signal_name': value} dict with signal states
        """
        state_dict = {}
        for signal in self.signals:
            state_dict[signal.name] = signal.get_state()
        return state_dict

    def add_self_to_plot(self, ax: Axes3D, axis_scale_unit: Unit) -> None:
        # docstring inherited from InterfaceDevice
        marker = ax.scatter(
            self.xs / axis_scale_unit,
            self.ys / axis_scale_unit,
            self.zs / axis_scale_unit,
            marker="x",
            s=40,
            color="xkcd:dark gray",
            label=self.name,
            depthshade=False,
        )
        handles = ax.get_legend().legendHandles
        handles.append(marker)
        ax.legend(handles=handles)

    @property
    def xs(self) -> Quantity:
        """x coordinates of recording contacts

        Returns
        -------
        Quantity
            x coordinates represented as a Brian quantity, that is,
            including units. Should be like a 1D array.
        """
        return self.coords[:, 0]

    @property
    def ys(self) -> Quantity:
        """y coordinates of recording contacts

        Returns
        -------
        Quantity
            y coordinates represented as a Brian quantity, that is,
            including units. Should be like a 1D array.
        """
        return self.coords[:, 1]

    @property
    def zs(self) -> Quantity:
        """z coordinates of recording contacts

        Returns
        -------
        Quantity
            z coordinates represented as a Brian quantity, that is,
            including units. Should be like a 1D array.
        """
        return self.coords[:, 2]

    def reset(self, **kwargs):
        """Reset the probe to a neutral state

        Calls reset() on each signal
        """
        for signal in self.signals:
            signal.reset()


def concat_coords(*coords: Quantity) -> Quantity:
    """Combine multiple coordinate Quantity arrays into one

    Parameters
    ----------
    *coords : Quantity
        Multiple coordinate n x 3 Quantity arrays to combine

    Returns
    -------
    Quantity
        A single n x 3 combined Quantity array
    """
    out = np.vstack([c / mm for c in coords])
    return out * mm


def linear_shank_coords(
    array_length: Quantity,
    channel_count: int,
    start_location: Quantity = (0, 0, 0) * mm,
    direction: Tuple[float, float, float] = (0, 0, 1),
) -> Quantity:
    """Generate coordinates in a linear pattern

    Parameters
    ----------
    array_length : Quantity
        Distance from the first to the last contact (with
        a Brian unit)
    channel_count : int
        Number of coordinates to generate, i.e. electrode contacts
    start_location : Quantity, optional
        x, y, z coordinate (with unit) for the start of the electrode
        array, by default (0, 0, 0)*mm
    direction : Tuple[float, float, float], optional
        x, y, z vector indicating the direction in which the array
        extends, by default (0, 0, 1), meaning pointing straight down

    Returns
    -------
    Quantity
        channel_count x 3 array of coordinates, where the 3 columns
        represent x, y, and z
    """
    dir_uvec = direction / np.linalg.norm(direction)
    end_location = start_location + array_length * dir_uvec
    return np.linspace(start_location, end_location, channel_count)


def tetrode_shank_coords(
    array_length: Quantity,
    tetrode_count: int,
    start_location: Quantity = (0, 0, 0) * mm,
    direction: Tuple[float, float, float] = (0, 0, 1),
    tetrode_width: Quantity = 25 * umeter,
) -> Quantity:
    """Generate coordinates for a linear array of tetrodes

    See https://www.neuronexus.com/products/electrode-arrays/up-to-15-mm-depth
    to visualize NeuroNexus-style arrays.

    Parameters
    ----------
    array_length : Quantity
        Distance from the center of the first tetrode to the
        last (with a Brian unit)
    tetrode_count : int
        Number of tetrodes desired
    start_location : Quantity, optional
        Center location of the first tetrode in the array,
        by default (0, 0, 0)*mm
    direction : Tuple[float, float, float], optional
        x, y, z vector determining the direction in which the linear
        array extends, by default (0, 0, 1), meaning straight down.
    tetrode_width : Quantity, optional
        Distance between contacts in a single tetrode. Not the diagonal
        distance, but the length of one side of the square. By default
        25*umeter, as in NeuroNexus probes.

    Returns
    -------
    Quantity
        (tetrode_count*4) x 3 array of coordinates, where 3 columns
        represent x, y, and z
    """
    dir_uvec = direction / np.linalg.norm(direction)
    end_location = start_location + array_length * dir_uvec
    center_locs = np.linspace(start_location, end_location, tetrode_count)
    # need to add coords around the center locations
    # tetrode_width is the length of one side of the square, so the diagonals
    # are measured in width/sqrt(2)
    #    x      -dir*width/sqrt(2)
    # x  .  x   +/- orth*width/sqrt(2)
    #    x      +dir*width/sqrt(2)
    orth_uvec, _ = get_orth_vectors_for_v(dir_uvec)
    return np.repeat(center_locs, 4, axis=0) + tetrode_width / np.sqrt(2) * np.tile(
        np.vstack([-dir_uvec, -orth_uvec, orth_uvec, dir_uvec]), (tetrode_count, 1)
    )


def poly2_shank_coords(
    array_length: Quantity,
    channel_count: int,
    intercol_space: Quantity,
    start_location: Quantity = (0, 0, 0) * mm,
    direction: Tuple[float, float, float] = (0, 0, 1),
) -> Quantity:
    """Generate NeuroNexus-style Poly2 array coordinates

    Poly2 refers to 2 parallel columns with staggered contacts.
    See https://www.neuronexus.com/products/electrode-arrays/up-to-15-mm-depth
    for more detail.

    Parameters
    ----------
    array_length : Quantity
        Length from the beginning to the end of the two-column
        array, as measured in the center
    channel_count : int
        Total (not per-column) number of coordinates (recording contacts) desired
    intercol_space : Quantity
        Distance between columns (with Brian unit)
    start_location : Quantity, optional
        Where to place the beginning of the array, by default (0, 0, 0)*mm
    direction : Tuple[float, float, float], optional
        x, y, z vector indicating the direction in which the two columns
        extend; by default (0, 0, 1), meaning straight down.

    Returns
    -------
    Quantity
        channel_count x 3 array of coordinates, where the 3 columns
        represent x, y, and z
    """
    dir_uvec = direction / np.linalg.norm(direction)
    end_location = start_location + array_length * dir_uvec
    out = np.linspace(start_location, end_location, channel_count)
    orth_uvec, _ = get_orth_vectors_for_v(dir_uvec)
    # place contacts on alternating sides of the central axis
    even_channels = np.arange(channel_count) % 2 == 0
    out[even_channels] += intercol_space / 2 * orth_uvec
    out[~even_channels] -= intercol_space / 2 * orth_uvec
    return out


def poly3_shank_coords(
    array_length: Quantity,
    channel_count: int,
    intercol_space: Quantity,
    start_location: Quantity = (0, 0, 0) * mm,
    direction: Tuple[float, float, float] = (0, 0, 1),
) -> Quantity:
    """Generate NeuroNexus Poly3-style array coordinates

    Poly3 refers to three parallel columns of electrodes.
    The middle column will be longest if the channel count
    isn't divisible by three and the side columns will be
    centered vertically with respect to the middle.

    Parameters
    ----------
    array_length : Quantity
        Length from beginning to end of the array as measured
        along the center column
    channel_count : int
        Total (not per-column) number of coordinates to generate
        (i.e., electrode contacts)
    intercol_space : Quantity
        Spacing between columns, with Brian unit
    start_location : Quantity, optional
        Location of beginning of the array, that is, the first contact
        in the center column, by default (0, 0, 0)*mm
    direction : Tuple[float, float, float], optional
        x, y, z vector indicating the direction along which the
        array extends, by default (0, 0, 1), meaning straight down

    Returns
    -------
    Quantity
        channel_count x 3 array of coordinates, where the 3 columns
        represent x, y, and z
    """
    # makes middle column longer if not even. Nothing fancier.
    # length measures middle column
    dir_uvec = direction / np.linalg.norm(direction)
    end_location = start_location + array_length * dir_uvec
    center_loc = start_location + array_length * dir_uvec / 2
    n_middle = channel_count // 3 + channel_count % 3
    n_side = int((channel_count - n_middle) / 2)

    middle = np.linspace(start_location, end_location, n_middle)

    spacing = array_length / n_middle
    side_length = n_side * spacing
    orth_uvec, _ = get_orth_vectors_for_v(dir_uvec)
    side = np.linspace(
        center_loc - dir_uvec * side_length / 2,
        center_loc + dir_uvec * side_length / 2,
        n_side,
    )
    side1 = side + orth_uvec * intercol_space
    side2 = side - orth_uvec * intercol_space
    out = concat_coords(middle, side1, side2)
    return out[out[:, 2].argsort()]  # sort to return superficial -> deep


def tile_coords(coords: Quantity, num_tiles: int, tile_vector: Quantity) -> Quantity:
    """Tile (repeat) coordinates to produce multi-shank/matrix arrays

    Parameters
    ----------
    coords : Quantity
        The n x 3 coordinates array to tile
    num_tiles : int
        Number of times to tile (repeat) the coordinates. For example,
        if you are tiling linear shank coordinates to produce multi-shank
        coordinates, this would be the desired number of shanks
    tile_vector : Quantity
        x, y, z array with Brian unit determining both the length
        and direction of the tiling

    Returns
    -------
    Quantity
        (n * num_tiles) x 3 array of coordinates, where the 3 columns
        represent x, y, and z
    """
    num_coords = coords.shape[0]
    # num_tiles X 3
    offsets = np.linspace((0, 0, 0) * mm, tile_vector, num_tiles)
    # num_coords X num_tiles X 3
    out = np.tile(coords[:, np.newaxis, :], (1, num_tiles, 1)) + offsets
    return out.reshape((num_coords * num_tiles, 3), order="F")
