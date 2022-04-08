"""Data extraction from widefield binary file"""

import logging
import numpy as np
import shutil

import ibllib.dsp as dsp
import ibllib.exceptions as err
from ibllib.io.extractors.base import BaseExtractor
from ibllib.io.extractors.ephys_fpga import get_main_probe_sync, get_sync_fronts
from ibllib.io.video import get_video_meta

import wfield.cli as wfield_cli
from labcams.io import parse_cam_log


_logger = logging.getLogger('ibllib')
FILENAME_MAP = {
    'frames_average.npy': ('widefieldChannels.frameAverage.npy', 'raw_widefield_data'),
    'U.npy': ('widefieldU.images.npy', 'alf'),
    'SVT.npy': ('widefieldSVT.uncorrected.npy', 'alf'),
    'SVTcorr.npy': ('widefieldSVT.haemoCorrected.npy', 'alf'),

    # Below here keep for now, but probably don't need to rename or register
    # 'U-warped.npy': 'widefieldU.images_atlas_corrected.npy' # TODO need to see if we need this
    # 'rcoeffs.npy': 'rcoeffs.npy',
    # 'T.npy': 'widefieldT.uncorrected.npy',
    # 'motioncorrect_*.bin': 'widefield.motionCorrected.bin',
    # 'motion_correction_shifts.npy': 'widefield.motionCorrectionShifts.npy',
    # 'motion_correction_rotation.npy': 'widefield.motionCorrectionRotation.npy',
}


class Widefield(BaseExtractor):
    save_names = (None, None, None, 'widefieldChannels.frameAverage.npy', 'widefieldU.images.npy', 'widefieldSVT.uncorrected.npy',
                  None, None, 'widefieldSVT.haemoCorrected.npy', 'widefield.times', 'widefield.widefieldLightSource')
    raw_names = ('motioncorrect_2_540_640_uint16.bin', 'motion_correction_shifts.npy', 'motion_correction_rotation.npy',
                 'frames_average.npy', 'U.npy', 'SVT.npy', 'rcoeffs.npy', 'T.npy', 'SVTcorr.npy', 'timestamps.npy', 'led.npy')
    var_names = ()

    def __init__(self, *args, **kwargs):
        """An extractor for all widefield data"""
        super().__init__(*args, **kwargs)
        self.data_path = self.session_path.joinpath('raw_widefield_data')

    def _extract(self, extract_timestamps=True, save=False, **kwargs):
        """
        NB: kwargs should be loaded from meta file
        Parameters
        ----------
        n_channels
        dtype
        shape
        kwargs

        Returns
        -------

        """
        self.preprocess(**kwargs)
        if extract_timestamps:
            _ = self.sync_timestamps(save=save)

        return None

    def _save(self, data=None, path_out=None):

        if not path_out:
            path_out = self.session_path.joinpath(self.default_path)
        path_out.mkdir(exist_ok=True, parents=True)

        new_files = []
        if not self.data_path.exists():
            _logger.warning(f'Path does not exist: {self.data_path}')
            return new_files

        for before, after in zip(self.raw_names, self.save_names):
            if after is None:
                continue
            else:
                try:
                    file_orig = next(self.data_path.glob(before))
                    file_new = path_out.joinpath(after)
                    shutil.move(file_orig, file_new)
                    new_files.append(file_new)
                except StopIteration:
                    _logger.warning(f'File not found: {before}')

        return new_files

    def preprocess(self, fs=30, functional_channel=0, nbaseline_frames=30, k=200):

        # MOTION CORRECTION
        wfield_cli._motion(str(self.data_path))
        # COMPUTE AVERAGE FOR BASELINE
        wfield_cli._baseline(str(self.data_path), nbaseline_frames)
        # DATA REDUCTION
        wfield_cli._decompose(str(self.data_path), k=k)
        # HAEMODYNAMIC CORRECTION
        # check if it is 2 channel
        dat = wfield_cli.load_stack(str(self.data_path))
        if dat.shape[1] == 2:
            del dat
            wfield_cli._hemocorrect(str(self.data_path), fs=fs, functional_channel=functional_channel)

    def remove_files(self, file_prefix='motion'):
        motion_files = self.data_path.glob(f'{file_prefix}*')
        for file in motion_files:
            _logger.info(f'Removing {file}')
            file.unlink()

    def sync_timestamps(self, bin_exists=False, save=False, save_paths=None):

        if save and save_paths:
            assert len(save_paths) == 2, 'Must provide save_path as list with 2 paths'

        filepath = next(self.data_path.glob('*.camlog'))
        fpga_sync, chmap = get_main_probe_sync(self.session_path, bin_exists=bin_exists)
        bpod = get_sync_fronts(fpga_sync, chmap['bpod'])
        logdata, led, sync, ncomm = parse_cam_log(filepath, readTeensy=True)
        if bpod.times.size == 0:
            raise err.SyncBpodFpgaException('No Bpod event found in FPGA. No behaviour extraction. '
                                            'Check channel maps.')
        # convert to seconds
        fcn, drift, iteensy, ifpga = dsp.utils.sync_timestamps(sync.timestamp.values / 1e3, bpod['times'], return_indices=True)

        _logger.debug(f'Widefield-FPGA clock drift: {drift} ppm')
        assert led.frame.is_monotonic_increasing
        video_path = next(self.data_path.glob('widefield.raw*.mov'))
        video_meta = get_video_meta(video_path)

        diff = len(led) - video_meta.length
        if diff < 0:
            raise ValueError('More frames than timestamps detected')
        if diff > 2:
            raise ValueError('Timestamps and frames differ by more than 2')

        led = led[0:video_meta.length]
        # just gonna take the first led times for the frames
        widefield_times = fcn(led.timestamp.values / 1e3)
        widefield_leds = led.led

        if save:
            save_time = save_paths[0] if save_paths else self.data_path.joinpath('timestamps.npy')
            save_led = save_paths[1] if save_paths else self.data_path.joinpath('led.npy')
            save_paths = [save_time, save_led]
            np.save(save_time, widefield_times)
            np.save(save_led, widefield_leds)

            return save_paths
        else:
            return widefield_times, widefield_leds
