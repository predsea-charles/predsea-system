# 03. Thermodynamics & Bulk Surface Fluxes

This document details the thermodynamic formulations, air-sea boundary layer bulk parameterizations, and numerical bug fixes implemented in **PredSea** to eliminate unphysical heat accumulation in regional hydrodynamic runs.

---

## 1. Governing Heat Flux Equations

The net surface heat flux ($\text{shflux}$, expressed in $\text{W/m}^2$) entering or leaving the upper oceanic boundary layer is defined by the algebraic sum of shortwave solar radiation, net longwave thermal radiation, latent heat flux from evaporation, and sensible turbulent heat flux:

$$\text{shflux} = \text{radsw} + \text{shflx\_rlw} + \text{shflx\_lat} + \text{shflx\_sen}$$

Where sign convention dictates that **positive values ($>0$) represent heat gain by the ocean**, and **negative values ($<0$) represent net heat loss from the ocean to the atmosphere**.

```
                         Atmosphere
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
   radsw (SW v)   shflx_rlw (LW ^)   shflx_lat (E ^)   shflx_sen (H ^)
     [+ Solar]     [- Longwave]       [- Evaporation]   [- Conduction]
         |              ^                  ^                 ^
         v              |                  |                 |
================================================~~~~~~~~~~~~~~~ (Sea Surface)
                       Ocean Mixed Layer
```

### A. Net Shortwave Solar Radiation ($\text{radsw}$)
Shortwave solar flux reaching the surface mixed layer is governed by downward shortwave flux ($SW_{\downarrow}$) modulated by the sea surface albedo ($\alpha \approx 0.06$):

$$\text{radsw} = (1 - \alpha) \cdot SW_{\downarrow}$$

Shortwave radiation penetrates the upper water column following a two-band exponential decay attenuation model:

$$I(z) = \text{radsw} \cdot \left[ r_1 e^{z / d_1} + (1 - r_1) e^{z / d_2} \right]$$

Where $r_1 \approx 0.58$ represents the rapidly absorbed infrared spectrum fraction ($d_1 \approx 0.35\text{ m}$), and $(1-r_1)$ is the blue-green spectrum with deeper optical attenuation scale ($d_2 \approx 23.0\text{ m}$ in clear Mediterranean waters).

### B. Net Longwave Infrared Radiation ($\text{shflx\_rlw}$)
Net longwave flux represents the balance between incoming atmospheric downward thermal radiation ($LW_{\downarrow}$) and Stefan-Boltzmann blackbody radiation emitted by the sea surface temperature ($\text{SST}$):

$$\text{shflx\_rlw} = \epsilon_s LW_{\downarrow} - \epsilon_s \sigma_{SB} \cdot (\text{SST} + 273.15)^4$$

Where:
*   $\epsilon_s = 0.98$ is the ocean emissivity constant.
*   $\sigma_{SB} = 5.670374 \times 10^{-8} \, \text{W/m}^2/\text{K}^4$ is the Stefan-Boltzmann constant.

Because Mediterranean summer sea surface temperatures ($\text{SST} \approx 26^\circ\text{C} - 29^\circ\text{C}$) typically exceed near-surface air temperatures, $\text{shflx\_rlw}$ acts as a continuous cooling mechanism (ranging between $-50\text{ W/m}^2$ and $-110\text{ W/m}^2$).

### C. Latent Heat Flux ($\text{shflx\_lat}$)
Latent heat flux driven by wind-induced surface evaporation is parameterized using COARE 3.0 bulk aerodynamic formulas:

$$\text{shflx\_lat} = -\rho_a L_v C_E \cdot |\vec{U}_{10}| \cdot \left( q_s(\text{SST}) - q_a \right)$$

Where:
*   $\rho_a$ is air density ($\approx 1.22\text{ kg/m}^3$).
*   $L_v$ is latent heat of vaporization ($\approx 2.45 \times 10^6 \, \text{J/kg}$).
*   $C_E$ is the turbulent transfer coefficient for moisture.
*   $|\vec{U}_{10}|$ is $10\text{ m}$ wind speed magnitude.
*   $q_s(\text{SST})$ is saturation specific humidity at sea surface temperature.
*   $q_a$ is atmospheric specific humidity at $2\text{ m}$.

### D. Sensible Heat Flux ($\text{shflx\_sen}$)
Direct conductive/convective heat exchange between ocean and air is governed by:

$$\text{shflx\_sen} = -\rho_a c_p C_H \cdot |\vec{U}_{10}| \cdot \left( \text{SST} - T_a \right)$$

Where $c_p = 1004.6 \, \text{J/kg/K}$ is atmospheric specific heat capacity and $C_H$ is the bulk sensible heat transfer coefficient.

---

## 2. Verified Fix: Bulk Flux Sign-Convention Correction in `bulk_flux.F`

The one thermodynamics fix actually present in this codebase (`simulation/marine/croco/patch_croco_source.py`, applied to `bulk_flux.F` at build time for every region) corrects the sign convention on latent and sensible heat flux, not a unit-scaling or SST-feedback bug. The original CROCO source computed:

```fortran
hflat=-hflat*rho0i*cpi
hfsen=-hfsen*rho0i*cpi
```

This unconditionally negates whatever sign the underlying bulk formula produced, with no guarantee that latent/sensible flux actually points the physically required direction (evaporation must always remove heat from the ocean; conduction must remove heat from the ocean whenever the sea is warmer than the air). The applied patch enforces that directionality explicitly:

```fortran
! --- FIXED SIGN CONVENTION FOR BULK FLUXES ---
! 1. Latent Heat Flux: Evaporation MUST remove energy from ocean (< 0)
hflat=-ABS(hflat)*rho0i*cpi
! 2. Sensible Heat Flux: Conduction when SST > T_air MUST remove energy from ocean (< 0)
IF (TseaC .gt. TairC) THEN
  hfsen=-ABS(hfsen)*rho0i*cpi
ELSE
  hfsen=-hfsen*rho0i*cpi
ENDIF
```

This is a narrower, more mechanical fix than a full unit-mismatch or dynamic-SST-feedback correction — it guards against one specific failure mode (a sign flip producing spurious ocean warming from evaporation/conduction) rather than rewriting the bulk flux calculation. Whether this alone was sufficient to prevent the thermal runaway seen in early pre-alpha runs, versus other contributing factors (e.g. the vertical-coordinate/barotropic-transport fixes in `prepare_croco_forcing.py` described in Section 2 of `02_modeling_suite.md`), has not been isolated by a controlled test; both changes shipped together in the runs validated so far.

---

## 3. Nocturnal Boundary Cooling Mechanics

The resolution of `bulk_flux.F` restores physical nocturnal cooling. During daytime hours, solar flux ($\text{radsw}$) dominates, producing a positive net flux ($\text{shflux} \approx +400\text{ W/m}^2 \text{ to } +700\text{ W/m}^2$) that warms the top $1\text{ m} - 3\text{ m}$ diurnal skin layer.

During night hours ($SW_{\downarrow} = 0$), $\text{radsw}$ drops to zero. Net surface heat flux becomes strictly negative:

$$\text{shflux}_{\text{night}} = \text{shflx\_rlw} + \text{shflx\_lat} + \text{shflx\_sen} \approx -180\text{ W/m}^2 \text{ to } -320\text{ W/m}^2$$

```
+-----------------------------------------------------------------------------------+
|                        Diurnal Surface Heat Flux Cycle                            |
|                                                                                   |
|  Flux (W/m2)                                                                      |
|   +800 |                     /---\ (Daytime Solar Peak)                           |
|   +600 |                    /     \                                               |
|   +400 |                   /       \                                              |
|   +200 |                  /         \                                             |
|      0 +-----------------/-----------\------------------+-----------------------  |
|   -200 |======= (Nocturnal Cooling: -220 W/m2) =========|                         |
|   -400 |                                                                          |
|        +----------------+------------+------------------+--------------------->   |
|        00:00           06:00        12:00              18:00            24:00 UTC |
+-----------------------------------------------------------------------------------+
```

This negative nocturnal flux generates surface water density inversion ($\frac{\partial \rho}{\partial z} < 0$), triggering convective vertical mixing that cools the surface layer back toward equilibrium baseline temperatures. Confirming this quantitatively against satellite radiometry or buoy observations for the Western Mediterranean has not yet been done — see `04_empirical_validation.md` for what has actually been measured so far.
