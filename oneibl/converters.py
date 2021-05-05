"""
A module for inter-converting experiment identifiers.

There are multiple ways to uniquely identify an experiment:
    - eid (str) : An experiment UUID as a string
    - np (int16) : An experiment UUID encoded as 2 int16s
    - path (Path) : A pathlib ALF path of the form <lab>/Subjects/<subject>/<date>/<number>
    - ref (str) : An experiment reference string of the form yyyy-mm-dd_n_subject
    - url (str) : An remote http session path of the form <lab>/Subjects/<subject>/<date>/<number>
"""
import functools
from inspect import getmembers, isfunction
from pathlib import Path, PurePosixPath
from typing import Optional, Union, Sequence, Mapping, Iterable

import numpy as np

import alf.io as alfio
from brainbox.io import parquet

def Listable(t): return Union[t, Sequence[t]]  # noqa


def recurse(func):
    @functools.wraps(func)
    def wrapper_decorator(*args, **kwargs):
        first, *args = args
        if isinstance(first, Iterable) and not isinstance(first, (str, Mapping)):
            return [func(item, *args, **kwargs) for item in first]
        else:
            return func(first, *args, **kwargs)
    return wrapper_decorator


class ConversionMixin:

    def __init__(self):
        self._cache = None
        self._index_type = None
        self._par = None

    # def to_eid(self, id):
    #     pass

    def path_from_eid(self, eid: str) -> Optional[Listable(Path)]:
        """
        From an experiment id or a list of experiment ids, gets the local cache path
        :param eid: eid (UUID) or list of UUIDs
        :return: eid or list of eids
        """
        # If eid is a list of eIDs recurse through list and return the results
        if isinstance(eid, list):
            path_list = []
            for p in eid:
                path_list.append(self.path_from_eid(p))
            return path_list
        # If not valid return None
        if not alfio.is_uuid_string(eid):
            raise ValueError(eid + " is not a valid eID/UUID string")
        if self._cache['sessions'].size == 0:
            return

        # load path from cache
        if self._index_type() is int:
            # ids = np.array(self._cache['sessions'].index.tolist())
            # ids = self._cache['sessions'].reset_index()[['eid_0', 'eid_1']].to_numpy()
            # ic = find_first_2d(ids, parquet.str2np(eid))
            # if ic is not None:
            #     ses = self._cache['sessions'].iloc[ic]
            eid = parquet.str2np(eid).tolist()
        try:
            ses = self._cache['sessions'].loc[eid]
            assert len(ses) == 1, 'Duplicate eids in sessions table'
            ses, = ses.to_dict('records')
            return Path(self._par.CACHE_DIR).joinpath(
                ses['lab'], 'Subjects', ses['subject'], ses['date'], str(ses['number']).zfill(3))
        except KeyError:
            return

    def eid_from_path(self, path_obj):
        """
        From a local path, gets the experiment id
        :param path_obj: local path or list of local paths
        :return: eid or list of eids
        """
        # If path_obj is a list recurse through it and return a list
        if isinstance(path_obj, list):
            path_obj = [Path(x) for x in path_obj]
            eid_list = []
            for p in path_obj:
                eid_list.append(self.eid_from_path(p))
            return eid_list
        # else ensure the path ends with mouse,date, number
        path_obj = Path(path_obj)
        session_path = alfio.get_session_path(path_obj)
        sessions = self._cache['sessions']

        # if path does not have a date and a number, or cache is empty return None
        if session_path is None or sessions.size == 0:
            return None

        # reduce session records from cache
        subject, date, number = session_path.parts[-3:]
        for col, val in zip(('subject', 'date', 'number'), (subject, date, int(number))):
            sessions = sessions[sessions[col] == val]
            if sessions.size == 0:
                return

        assert len(sessions) == 1

        eid, = sessions.index.values
        if isinstance(eid, tuple):
            eid = parquet.np2str(np.array(eid))
        return eid

    def record_from_path(self, filepath):
        """
        NB: Assumes <lab>/Subjects/<subject>/<date>/<number> pattern
        :param filepath: File path or http URL
        :return:
        """
        if isinstance(filepath, str) and filepath.startswith('http'):
            # Remove the UUID from path
            filepath = alfio.remove_uuid_file(PurePosixPath(filepath), dry=True)
        session_path = '/'.join(alfio.get_session_path(filepath).parts[-5:])
        rec = self._cache['datasets']
        rec = rec[rec['session_path'] == session_path]
        rec = rec[rec['rel_path'].apply(lambda x: filepath.as_posix().endswith(x))]
        return None if len(rec) == 0 else rec

    def url_from_path(self, filepath):
        """
        Given a local file path, constructs the URL of the remote file.
        :param filepath: A local file path
        :return: A URL string
        """
        record = self.record_from_path(filepath)
        if record is None:
            return
        assert len(record) == 1
        uuid, = parquet.np2str(record.reset_index()[['dset_id_0', 'dset_id_1']])
        filepath = alfio.add_uuid_string(filepath, uuid).as_posix()
        root = self._par.CACHE_DIR.replace('\\', '/')
        assert filepath.startswith(root)
        return filepath.replace(root, self._par.HTTP_DATA_SERVER)

    def url_from_record(self, dataset):
        # for i, rec in dataset.iterrows():
        assert len(dataset) == 1
        # TODO This line will cahnge on id rename
        uuid, = parquet.np2str(dataset.reset_index()[['dset_id_0', 'dset_id_1']])
        session_path, rel_path = dataset[['session_path', 'rel_path']].to_numpy().flatten()
        url = PurePosixPath(session_path, rel_path)
        return self._par.HTTP_DATA_SERVER + '/' + alfio.add_uuid_string(url, uuid).as_posix()

    def path_from_record(self, dataset) -> Optional[Path]:
        """
        Given a set of dataset records, checks the corresponding exists flag in the cache
        correctly reflects the files system
        :param dataset: A datasets dataframe slice
        :return: File path for the record
        """
        assert len(dataset) == 1
        session_path, rel_path = dataset[['session_path', 'rel_path']].to_numpy().flatten()
        file = Path(self._par.CACHE_DIR, session_path, rel_path)
        return file  # files[0] if len(datasets) == 1 else files

    def path_from_url(self, url):
        import alf.files
        # alfio.

    def ref_from_eid(self, eid):
        pass

    def eid_from_ref(self, ref):
        pass

    def path_from_ref(self, ref):
        pass

    def pid_to_path(self, pid):
        pass


from_funcs = getmembers(ConversionMixin,
                        lambda x: isfunction(x) and '_from_' in x.__name__)
for name, fn in from_funcs:
    setattr(ConversionMixin, name, recurse(fn))  # Add recursion decorator
    attr = '{0}2{1}'.format(*name.split('_from_'))
    from_fn = getattr(ConversionMixin, '{1}_from_{0}'.format(*name.split('_from_')), None)
    if from_fn:
        setattr(ConversionMixin, attr, recurse(from_fn))  # Add 2 function alias