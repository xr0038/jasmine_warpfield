#!/usr/bin/env python
# -*- coding: utf-8 -*-
''' Handling astronomical sources '''

from dataclasses import dataclass, field
from astropy.coordinates import SkyCoord, Angle, Distance
from astropy.table import QTable
from astropy.time import Time
from astroquery.gaia import Gaia
import astropy.io.fits as fits
import astropy.units as u
import numpy as np

from .util import eprint


__debug_mode__ = False

__columns__ = {
    'source_id': None,
    'ra': 'degree',
    'ra_error': 'mas',
    'dec': 'degree',
    'dec_error': 'mas',
    'phot_g_mean_mag': 'mag',
    'phot_bp_mean_mag': 'mag',
    'phot_rp_mean_mag': 'mag',
    'pmra': 'mas/year',
    'pmra_error': 'mas/year',
    'pmdec': 'mas/year',
    'pmdec_error': 'mas/year',
    'parallax': 'mas',
    'parallax_error': 'mas',
    'ruwe': None,
    'non_single_star': None,
    'ref_epoch': 'year',
}


@dataclass(frozen=True)
class withFITSIO:
    ''' QTable with I/O functions

    Attributes:
      table (QTable):
          Table of celestial objects.
    '''
    table: QTable

    def __len__(self):
        return len(self.table)

    def __getitem__(self, key):
        return self.table[key]

    @staticmethod
    def from_fitsfile(filename, key='table'):
        ''' Generate a SourceTable from a FITS file '''
        hdul = fits.open(filename)
        table = QTable.read(hdul[key])
        return SourceTable(table=table)

    def writeto(self, filename, overwrite=False):
        ''' Dump a SourceTable into a FITS file

        Arguments:
          filename (str):
              A filename to be saved.

        Options:
          overwrite (bool):
              An existing file will be overwritten if true.
        '''
        hdul = fits.HDUList([
            fits.PrimaryHDU(),
            fits.BinTableHDU(data=self.table, name='table')
        ])
        hdul.writeto(filename, overwrite=overwrite)


def convert_skycoord_to_sourcetable(skycoord):
    return SourceTable(QTable([
        skycoord.icrs.ra,
        skycoord.icrs.dec,
    ], names=['ra', 'dec']))


@dataclass(frozen=True)
class SourceTable(withFITSIO):
    ''' Source Table

    Attributes:
      table (QTable):
          Table of celestial objects.
      skycoord (SkyCoord):
          Auto-generated SkyCoord object.

     The table should contain the following columns.

        - ra: right ascension
        - dec: declination
        - parallax: parallax
        - pmra: proper motion in right ascension (μα*)
        - pmdec: proper motion in declination (μδ)
        - ref_epoch: measurement epoch
    '''
    skycoord: SkyCoord = field(init=False)

    @staticmethod
    def __get_epoch(time):
        return Time(time, format='decimalyear', scale='tcb')

    def __post_init__(self):
        if 'ref_epoch' in self.table.colnames:
            epoch = self.__get_epoch(self.table['ref_epoch'].data)
        elif 'epoch' in self.table.colnames:
            epoch = self.__get_epoch(self.table['epoch'].data)
        else:
            # obstime is assumed to be J2000.0 if epoch is not given.
            epoch = self.__get_epoch(2000.0)
        try:
            pmra = self.table['pmra']
            pmdec = self.table['pmdec']
        except KeyError:
            # proper motion is set zero if not given.
            pmra = np.zeros(len(self.table)) * u.mas / u.year
            pmdec = np.zeros(len(self.table)) * u.mas / u.year
        try:
            distance = Distance(parallax=self.table['parallax'])
        except KeyError:
            # distance is not specified if parallax is not given.
            distance = None
        try:
            skycoord = SkyCoord(
                ra=self.table['ra'], dec=self.table['dec'],
                pm_ra_cosdec=pmra, pm_dec=pmdec,
                distance=distance, obstime=epoch)
            self.__set_skycoord(skycoord)
        except KeyError as e:
            eprint(f'skip updating `skycoord` since {e} is not given.')
            self.__set_skycoord(None)

    def __set_skycoord(self, skycoord):
        object.__setattr__(self, 'skycoord', skycoord)

    def apply_space_motion(self, epoch):
        try:
            skycoord = self.skycoord.apply_space_motion(epoch)
            self.__set_skycoord(skycoord)
        except Exception as e:
            eprint(str(e))
            eprint('No proper motion information is available.')
            eprint('The positions are not updated to new epoch.')


@dataclass(frozen=True)
class FocalPlanePositionTable(SourceTable):
    def __post_init__(self):
        super().__post_init__()
        names = self.table.colnames
        assert 'x' in names
        assert 'y' in names


@dataclass(frozen=True)
class DetectorPositionTable(FocalPlanePositionTable):
    def __post_init__(self):
        super().__post_init__()
        names = self.table.colnames
        assert 'nx' in names
        assert 'ny' in names


def gaia_query_builder(
        pointing, radius, snr_limit, catalog='gaiadr3.gaia_source'):
    ''' Construct a query string

    Arguments:
      pointing: A center of the search circle.
      radius: A serach radius.
      snr_limit: A lower limit of `parallax_over_error`.
      catalog: The name of catalog (default: `gaiadr3.gaia_source`)

    Returns:
      A SQL query string.
    '''
    return f'''
    SELECT
        {','.join(__columns__.keys())}
    FROM
        {catalog}
    WHERE
        1=CONTAINS(
          POINT('ICRS', {pointing.icrs.ra.deg}, {pointing.icrs.dec.deg}),
          CIRCLE('ICRS', ra, dec, {radius.deg}))
    AND
        parallax_over_error > {snr_limit}
    '''


def retrieve_gaia_sources(pointing, radius, snr_limit=10.0, row_limit=-1):
    ''' Retrive sources around (lon, lat) from Gaia EDR3 catalog

    Arguments:
      pointing (SkyCoord):
          Celestial coordinates of the search center.
      radius (float or Angle):
          A search radius in degree.
      snr_limit (float, optional):
          A lower limit of `parallax_over_error`.
      row_limit (int, optional):
          The maximum number of records.
          `-1` means no limit in the number of records.

    Return:
      A table containig souces wihtin the search circle.
    '''

    # Get an acceess to the Gaia TAP+.
    #   - Set the target table to Gaia DR3.
    #   - Remove the limit of the query number.
    Gaia.MAIN_GAIA_TABLE = 'gaiadr3.gaia_source'
    Gaia.ROW_LIMIT = row_limit

    if not isinstance(radius, Angle):
        radius = Angle(radius, unit=u.degree)

    pointing = pointing.transform_to('icrs')
    query = gaia_query_builder(pointing, radius, snr_limit)

    res = Gaia.launch_job_async(query)

    if __debug_mode__ is True:
        print(res)

    record = res.get_results()
    record['non_single_star'] = record['non_single_star'] > 0
    return SourceTable(QTable(record))
