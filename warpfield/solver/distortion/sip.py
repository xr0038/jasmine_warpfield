#!/usr/bin/env python
# -*- coding: utf-8 -*-
''' distortion function defined by the SIP convention '''

from jax.lax import scan
import jax.numpy as jnp


def polymap(coeff, xy):
    ''' calculate a two-dimensional polynomical expansion

    Args:
      coeff: coefficients of a polynomial expansion.
      xy: original coordinates on the focal plane.

    Returns:
      (N,2) list of converted coordinates.
    '''

    def inner(order, coeff):
        ''' inner function to calculate a polynomical expansion

        Args:
          order: (m,n) integer power index pair.
          coeff: scale coefficient.

        Returns:
          calclated cordinates (p * x**m * y**n).
        '''
        m, n = order
        return [m - 1, n + 1], coeff * xy[:, 0]**m * xy[:, 1]**n

    _, pq = scan(inner, [len(coeff) - 1, 0], coeff)
    return pq.sum(axis=0)


def distortion(sip_a, sip_b, xy):
    ''' distort the coordinates using the SIP coefficients

    The SIP coefficients sip_a and sip_b should contains 18 coefficients.
    The coefficients do not contain the Affine-transformation term.

    - elements 0-2:   second order coefficients
    - elements 3-6:   third order coefficients
    - elements 7-11:  fourth order coefficients
    - elements 12-17: fifth order coefficients

    Args:
      sip_a: 5th-order SIP coefficients.
      sip_b: 5th-order SIP coefficients.
      xy: coordinates on the focal plane.

    Returns:
      distorted coordinates on the focal plane.
    '''
    scale = jnp.exp(-np.log(10)*4*np.array([2,2,2,3,3,3,3,4,4,4,4,4,5,5,5,5,5,5]))
    sip_a *= scale
    sip_b *= scale
    dx = polymap(sip_a[0:3], xy) + polymap(sip_a[3:7], xy) \
      + polymap(sip_a[7:12], xy) + polymap(sip_a[12:18], xy)
    dy = polymap(sip_b[0:3], xy) + polymap(sip_b[3:7], xy) \
      + polymap(sip_b[7:12], xy) + polymap(sip_b[12:18], xy)
    return xy + jnp.stack([dx, dy]).T
