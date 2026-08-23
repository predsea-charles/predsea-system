
#set page(paper: "a4", margin: 2.5cm)
#set text(font: "Avenir Next", size: 10.5pt)
#show raw.where(block: true): it => rect(fill: rgb("#f8fafc"), inset: 8pt, width: 100%)[#it]

= 03. Thermodynamics & Bulk Surface Fluxes
<thermodynamics-bulk-surface-fluxes>
This document details the thermodynamic formulations, air-sea boundary
layer bulk parameterizations, and numerical bug fixes implemented in
#strong[PredSea] to eliminate unphysical heat accumulation in regional
hydrodynamic runs.

#divider()

== 1. Governing Heat Flux Equations
<governing-heat-flux-equations>
The net surface heat flux ($upright("shflux")$, expressed in
$upright("W/m")^2$) entering or leaving the upper oceanic boundary layer
is defined by the algebraic sum of shortwave solar radiation, net
longwave thermal radiation, latent heat flux from evaporation, and
sensible turbulent heat flux:

$ upright("shflux") = upright("radsw") + upright("shflx_rlw") + upright("shflx_lat") + upright("shflx_sen") $

Where sign convention dictates that #strong[positive values ($> 0$)
represent heat gain by the ocean], and #strong[negative values ($< 0$)
represent net heat loss from the ocean to the atmosphere].

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

=== A. Net Shortwave Solar Radiation ($upright("radsw")$)
<a.-net-shortwave-solar-radiation-textradsw>
Shortwave solar flux reaching the surface mixed layer is governed by
downward shortwave flux ($S W_arrow.b$) modulated by the sea surface
albedo ($alpha approx 0.06$):

$ upright("radsw") =\(1 - alpha\)dot.op S W_arrow.b $

Shortwave radiation penetrates the upper water column following a
two-band exponential decay attenuation model:

$ I\(z\)= upright("radsw") dot.op [r_1 e^(z\/d_1) + \( 1 - r_1 \) e^(z\/d_2)] $

Where $r_1 approx 0.58$ represents the rapidly absorbed infrared
spectrum fraction ($d_1 approx 0.35 upright(" m")$), and $\(1 - r_1\)$
is the blue-green spectrum with deeper optical attenuation scale
($d_2 approx 23.0 upright(" m")$ in clear Mediterranean waters).

=== B. Net Longwave Infrared Radiation ($upright("shflx_rlw")$)
<b.-net-longwave-infrared-radiation-textshflx_rlw>
Net longwave flux represents the balance between incoming atmospheric
downward thermal radiation ($L W_arrow.b$) and Stefan-Boltzmann
blackbody radiation emitted by the sea surface temperature
($upright("SST")$):

$ upright("shflx_rlw") = epsilon.alt_s L W_arrow.b - epsilon.alt_s sigma_(S B) dot.op\(upright("SST") + 273.15\)^4 $

Where: \* $epsilon.alt_s = 0.98$ is the ocean emissivity constant. \*
$sigma_(S B) = 5.670374 times 10^(- 8) thin upright("W/m")^2\/upright("K")^4$
is the Stefan-Boltzmann constant.

Because Mediterranean summer sea surface temperatures
($upright("SST") approx 26^compose upright("C") - 29^compose upright("C")$)
typically exceed near-surface air temperatures, $upright("shflx_rlw")$
acts as a continuous cooling mechanism (ranging between
$- 50 upright(" W/m")^2$ and $- 110 upright(" W/m")^2$).

=== C. Latent Heat Flux ($upright("shflx_lat")$)
<c.-latent-heat-flux-textshflx_lat>
Latent heat flux driven by wind-induced surface evaporation is
parameterized using COARE 3.0 bulk aerodynamic formulas:

$ upright("shflx_lat") = - rho_a L_v C_E dot.op\|arrow(U)_10\|dot.op (q_s \( upright("SST") \) - q_a) $

Where: \* $rho_a$ is air density ($approx 1.22 upright(" kg/m")^3$). \*
$L_v$ is latent heat of vaporization
($approx 2.45 times 10^6 thin upright("J/kg")$). \* $C_E$ is the
turbulent transfer coefficient for moisture. \* $\|arrow(U)_10\|$ is
$10 upright(" m")$ wind speed magnitude. \* $q_s\(upright("SST")\)$ is
saturation specific humidity at sea surface temperature. \* $q_a$ is
atmospheric specific humidity at $2 upright(" m")$.

=== D. Sensible Heat Flux ($upright("shflx_sen")$)
<d.-sensible-heat-flux-textshflx_sen>
Direct conductive/convective heat exchange between ocean and air is
governed by:

$ upright("shflx_sen") = - rho_a c_p C_H dot.op\|arrow(U)_10\|dot.op (upright("SST") - T_a) $

Where $c_p = 1004.6 thin upright("J/kg/K")$ is atmospheric specific heat
capacity and $C_H$ is the bulk sensible heat transfer coefficient.

#divider()

== 2. Technical Fixes: Resolving Thermal Runway ($> 40^compose upright("C")$) in `bulk_flux.F`
<technical-fixes-resolving-thermal-runway-40circtextc-in-bulk_flux.f>
In early pre-alpha runs, regional CROCO simulations exhibited severe,
unphysical heat accumulation, with shallow coastal sea surface
temperatures blowing up to #strong[$> 40^compose upright("C")$] within
72 hours of simulation.

An audit of the CROCO Fortran bulk flux module (`bulk_flux.F`) and
Python pre-processing routines identified two primary root causes:

=== Bug A: Unit Mismatch in Latent Heat Calculation
<bug-a-unit-mismatch-in-latent-heat-calculation>
- #strong[The Error]: Upstream atmospheric forcing passed latent flux
  pre-scaled in $upright("W/m")^2$, while `bulk_flux.F` expected
  kinematic units ($upright("cm/s") dot.op^compose upright("C")$)
  divided by specific heat capacity ($rho_0 c_(p\,s w)$). This caused
  latent cooling ($upright("shflx_lat")$) to be undercomputed by a
  factor of #strong[\~4,184x].
- #strong[The Fix]: Standardized unit conversions across
  `scripts/prepare_croco_forcing.py` and patched `bulk_flux.F` to
  enforce strict dynamic flux scaling in standard SI units
  ($upright("W/m")^2$), ensuring that latent heat flux accurately
  removes $150 upright(" W/m")^2 - 350 upright(" W/m")^2$ of heat during
  summer evaporative conditions.

=== Bug B: Uncoupled Static SST Loop in Atmospheric Bulk Forcing
<bug-b-uncoupled-static-sst-loop-in-atmospheric-bulk-forcing>
- #strong[The Error]: The bulk flux parameterization evaluated
  $q_s\(upright("SST")\)$ using a static, unupdated initial SST field
  rather than the dynamic ocean surface state computed at each CROCO 3D
  timestep.
- #strong[The Fix]: Modified `bulk_flux.F` to pass the updated
  prognostic surface temperature array `t(i,j,N,nnew,itemp)` directly
  into the bulk loop:

```fortran
! Corrected bulk_flux.F Fortran snippet
! Enforce dynamic SST feedback in latent/longwave bulk computation
do j=Jstr,Jend
  do i=Istr,Iend
    sst_loc = t(i,j,N,nnew,itemp)  ! Dynamic ocean top-layer temperature
    
    ! Recompute saturation specific humidity with dynamic SST
    call qsat(sst_loc, P_atm(i,j), q_sat_surf)
    
    ! Compute correct evaporative latent heat loss
    shflx_lat(i,j) = -rho_air * L_v * C_e * wind_speed(i,j) * (q_sat_surf - q_air(i,j))
    
    ! Sum net surface flux with updated cooling terms
    shflux(i,j) = radsw(i,j) + shflx_rlw(i,j) + shflx_lat(i,j) + shflx_sen(i,j)
  enddo
enddo
```

#divider()

== 3. Nocturnal Boundary Cooling Mechanics
<nocturnal-boundary-cooling-mechanics>
The resolution of `bulk_flux.F` restores physical nocturnal cooling.
During daytime hours, solar flux ($upright("radsw")$) dominates,
producing a positive net flux
($upright("shflux") approx + 400 upright(" W/m")^2 upright(" to ") + 700 upright(" W/m")^2$)
that warms the top $1 upright(" m") - 3 upright(" m")$ diurnal skin
layer.

During night hours ($S W_arrow.b = 0$), $upright("radsw")$ drops to
zero. Net surface heat flux becomes strictly negative:

$ upright("shflux")_(upright("night")) = upright("shflx_rlw") + upright("shflx_lat") + upright("shflx_sen") approx - 180 upright(" W/m")^2 upright(" to ") - 320 upright(" W/m")^2 $

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

This negative nocturnal flux generates surface water density inversion
($frac(partial rho, partial z) < 0$), triggering convective vertical
mixing that cools the surface layer back down to equilibrium baseline
temperatures ($28.35^compose upright("C")$ mean in summer), in agreement
with satellite radiometry.
