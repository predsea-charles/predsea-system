
#set page(paper: "a4", margin: 2.5cm)
#set text(font: "Avenir Next", size: 10.5pt)
#show raw.where(block: true): it => rect(fill: rgb("#f8fafc"), inset: 8pt, width: 100%)[#it]

= 02. Core Numerical Engines & Coupling Mechanisms
<core-numerical-engines-coupling-mechanisms>
This document provides a mathematical and functional analysis of the
core numerical modeling engines integrated into the #strong[PredSea]
forecasting suite: #strong[WRF] (atmospheric dynamics), #strong[CROCO]
(hydrodynamics), and #strong[SWAN] (spectral wave dynamics), alongside
their two-way and three-way coupling interfaces via the
#strong[OASIS3-MCT / COAWST] framework.

#divider()

== 1. Core Numerical Modeling Engines
<core-numerical-modeling-engines>
```
+-----------------------------------------------------------------------------------+
|                            PredSea Modeling Suite                                 |
|                                                                                   |
|  +--------------------+    +--------------------+    +-------------------------+  |
|  |     WRF v4.5       |    |    CROCO v2.1.3    |    |       SWAN v41.45       |  |
|  |  (Atmosphere 1km)  |    |  (Hydrodynamic 1km)|    |  (Spectral Waves 1km)   |  |
|  +---------+----------+    +---------+----------+    +------------+------------+  |
|            |                         |                            |               |
|            | Surface Fluxes          | Wave Radiation Stress      | Currents &    |
|            | (tau, shflux, SST)      | & Bottom Friction          | Sea Level     |
|            v                         v                            v               |
|  +-----------------------------------------------------------------------------+  |
|  |                       OASIS3-MCT / COAWST Coupler                           |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

=== A. WRF (Weather Research and Forecasting Model)
<a.-wrf-weather-research-and-forecasting-model>
The atmospheric component runs WRF v4.5, solving the fully compressible,
non-hydrostatic Euler primitive equations on a Arakawa-C grid using
terrain-following hydrostatic pressure vertical coordinates ($eta$).

- #strong[Primary Governing Variables]: 3D velocity vectors
  ($arrow(u)_a$), perturbation potential temperature ($theta'$),
  geopotential ($phi.alt'$), and surface pressure ($P_(a t m)$).
- #strong[Physical Parameterizations]:
  - #strong[Microphysics]: WSM6 (WRF Single-Moment 6-class scheme).
  - #strong[Planetary Boundary Layer (PBL)]: YSU (Yonsie University
    scheme) resolving atmospheric turbulence and surface momentum flux
    closure.
  - #strong[Radiation]: RRTMG longwave and shortwave schemes computing
    surface downward fluxes ($S W_arrow.b\,L W_arrow.b$).
- #strong[Output Parameters]: Provides $10 upright(" m")$ wind vectors
  ($U_10\,V_10$), $2 upright(" m")$ air temperature ($T_a$), specific
  humidity ($q_a$), surface pressure ($P_(a t m)$), and radiative fluxes
  ($S W_arrow.b\,L W_arrow.b$).

=== B. CROCO (Coastal and Regional Ocean Community Model)
<b.-croco-coastal-and-regional-ocean-community-model>
CROCO v2.1.3 is a free-surface, hydrostatic/non-hydrostatic 3D primitive
equation hydrodynamic model evolved from ROMS. It uses an Arakawa-C grid
in the horizontal and a general curvilinear, terrain-following
$s$-vertical coordinate system in the vertical.

==== Hydrodynamic Governing Equations
<hydrodynamic-governing-equations>
In Cartesian/curvilinear coordinates with terrain-following $s$-levels,
the Reynolds-averaged Navier-Stokes (RANS) momentum equations under the
Boussinesq and hydrostatic approximations are:

$ frac(partial u, partial t) + arrow(v) dot.op nabla u - f v = - 1 / rho_0 frac(partial p, partial x) + frac(partial, partial z) (K_m frac(partial u, partial z)) + cal(D)_u $

$ frac(partial v, partial t) + arrow(v) dot.op nabla v + f u = - 1 / rho_0 frac(partial p, partial y) + frac(partial, partial z) (K_m frac(partial v, partial z)) + cal(D)_v $

$ frac(partial p, partial z) = - rho g $

$ frac(partial u, partial x) + frac(partial v, partial y) + frac(partial w, partial z) = 0 $

Where: \* $u\,v\,w$ are the 3D fluid velocity components in $x\,y\,z$.
\* $f = 2 Omega sin phi.alt$ is the Coriolis parameter. \* $rho_0$ is
the reference ocean water density ($1025 upright(" kg/m")^3$). \* $K_m$
is the vertical eddy viscosity derived from GLS (Generic Length Scale)
$k$-$epsilon.alt$ or $k$-$omega$ turbulence closure. \*
$cal(D)_u\,cal(D)_v$ represent horizontal viscosity and dissipation
operator terms.

==== Stretched $s$-Vertical Coordinate System
<stretched-s-vertical-coordinate-system>
To resolve both deep ocean circulation and shallow coastal boundary
layers, CROCO employs a non-linear vertical transformation
(`NEW_S_COORD`):

$ z\(x\,y\,s\)= zeta\(x\,y\)+\[zeta\(x\,y\)+ h\(x\,y\)\]dot.op S\(x\,y\,s\) $

Where the non-linear stretching function $S\(x\,y\,s\)$ is governed by
parameters $theta_s$ (surface stretching), $theta_b$ (bottom
stretching), and $h_c$ (critical depth):

$ S\(x\,y\,s\)= frac(h_c s + h C\(s\), h_c + h) $

In the reference Balearic grid ($401 times 501$ horizontal grid at
$1 upright(" km")$ resolution), $N = 32$ vertical layers are configured
with $theta_s = 6.0$, $theta_b = 0.0$, and $h_c = 10 upright(" m")$.

=== C. SWAN (Simulating WAves Nearshore)
<c.-swan-simulating-waves-nearshore>
SWAN v41.45 is a third-generation spectral wave model that computes the
evolution of the 2D wave action density spectrum
$N\(sigma\,theta\;x\,y\,t\)$ over coastal and shelf sea environments:

$ N\(sigma\,theta\)= frac(E\(sigma\,theta\), sigma) $

Where $sigma$ is the relative wave intrinsic frequency and $theta$ is
the wave propagation direction.

==== Spectral Action Balance Equation
<spectral-action-balance-equation>
The governing wave transport equation in absolute Cartesian coordinates
is given by:

$ frac(partial N, partial t) + frac(partial, partial x)\(c_x N\)+ frac(partial, partial y)\(c_y N\)+ frac(partial, partial sigma)\(c_sigma N\)+ frac(partial, partial theta)\(c_theta N\)= S_(t o t) / sigma $

Where: \* $\(c_x\,c_y\)= arrow(c)_g + arrow(U)$ are the spatial
propagation velocity components (group velocity $arrow(c)_g$ plus
background current vector $arrow(U)$). \* $c_sigma\,c_theta$ represent
the propagation speeds in spectral frequency $sigma$ and direction
$theta$ (resolving current refraction and depth-induced shoaling). \*
$S_(t o t)$ is the total source/sink term:

$ S_(t o t) = S_(i n) + S_(n l 3) + S_(n l 4) + S_(d s) + S_(b o t) + S_(d b) $

Where $S_(i n)$ is wind input, $S_(n l 3)\,S_(n l 4)$ are 3-wave (triad)
and 4-wave (quadruplet) non-linear interactions, $S_(d s)$ is
whitecapping dissipation, $S_(b o t)$ is bottom friction, and $S_(d b)$
is depth-induced wave breaking.

#divider()

== 2. Inter-Model Exchange Dynamics (WRF - SWAN - CROCO)
<inter-model-exchange-dynamics-wrf---swan---croco>
The complete three-way feedback mechanism across WRF, SWAN, and CROCO
(ROMS) is illustrated in the architectural figure below:

#figure(image("./assets/wrf_swan_croco_coupling.png", alt: "WRF-SWAN-CROCO Inter-Model Exchange Dynamics"),
  caption: [
    WRF-SWAN-CROCO Inter-Model Exchange Dynamics
  ]
)

#emph[Figure 2.1: Inter-model exchange dynamics within the COAWST
framework, defining variable feedback paths between WRF (atmosphere),
SWAN (waves), and CROCO/ROMS (hydrodynamics).]

```mermaid
flowchart TD
    subgraph Atmosphere
        WRF["WRF (Weather Research & Forecasting)"]
    end

    subgraph Wave Dynamics
        SWAN["SWAN (Spectral Waves)"]
    end

    subgraph Hydrodynamics
        CROCO["CROCO / ROMS (Hydrodynamics)"]
    end

    %% WRF <-> CROCO
    WRF -- "Tau (Surface Stress) & Net Heat Flux" --> CROCO
    CROCO -- "Sea Surface Temp (SST)" --> WRF

    %% WRF <-> SWAN
    WRF -- "10m Wind Vectors (U10, V10)" --> SWAN
    SWAN -- "Sea Surface Roughness (z0)" --> WRF

    %% SWAN <-> CROCO
    SWAN -- "Wave Dir, Hgt, Len, Per, % Breaking, E_diss, Bot Orbital Vel" --> CROCO
    CROCO -- "Bathymetry, Bottom Elevation, Sea Level (Zeta), Currents (u,v)" --> SWAN
```

=== Detailed Directional Exchange Vector Breakdown
<detailed-directional-exchange-vector-breakdown>
==== 1. WRF $arrow.r$ CROCO (ROMS)
<wrf-rightarrow-croco-roms>
- #strong[Surface Stress ($tau$) & Net Heat Flux]: WRF provides
  atmospheric surface stress vectors ($tau_x\,tau_y$) and component
  radiative/turbulent heat fluxes
  ($upright("radsw")\,upright("shflx_rlw")\,upright("shflx_lat")\,upright("shflx_sen")$)
  to drive ocean surface momentum and mixed-layer thermodynamics in
  CROCO.

==== 2. CROCO (ROMS) $arrow.r$ WRF
<croco-roms-rightarrow-wrf>
- #strong[Sea Surface Temperature (SST)]: CROCO returns updated
  $1 upright(" km")$ spatial SST fields back to WRF. This dynamic SST
  feedback prevents atmospheric boundary layer temperature drift and
  corrects surface sensible/latent heat transfer coefficients.

==== 3. SWAN $arrow.r$ CROCO (ROMS)
<swan-rightarrow-croco-roms>
- #strong[Wave Parameters & Bottom Kinematics]: SWAN transmits surface
  and bottom wave direction, significant wave height ($H_s$), wavelength
  ($L$), peak period ($T_p$), percent wave breaking fraction, energy
  dissipation rate ($E_(d i s s)$), and bottom orbital velocity
  ($U_(b o t)$) into CROCO. These drive wave radiation stress gradients
  ($S_(x x)\,S_(x y)\,S_(y y)$) and enhance bottom boundary layer
  friction.

==== 4. CROCO (ROMS) $arrow.r$ SWAN
<croco-roms-rightarrow-swan>
- #strong[Hydrodynamic Conditions]: CROCO feeds updated bathymetry,
  bottom elevation changes, sea surface height ($zeta$), and 3D
  depth-averaged currents ($u\,v$) into SWAN. These adjust shallow-water
  shoaling limits, depth-induced wave breaking, and Doppler current
  refraction.

==== 5. SWAN $arrow.r$ WRF
<swan-rightarrow-wrf>
- #strong[Sea Surface Roughness ($z_0$)]: SWAN computes wave-age and
  steepness dependent aerodynamic surface roughness length ($z_0$) from
  significant wave height, length, and period, passing it to WRF to
  adjust atmospheric drag coefficients ($C_D$).

==== 6. WRF $arrow.r$ SWAN
<wrf-rightarrow-swan>
- #strong[Surface Wind Forcing ($U_10\,V_10$)]: WRF passes
  high-resolution $10 upright(" m")$ wind velocity vectors into SWAN to
  drive spectral wave growth ($S_(i n)$).

#divider()

== 3. Summary of Coupler Data Exchange Matrix
<summary-of-coupler-data-exchange-matrix>
#figure(
  align(center)[#table(
    columns: (19.05%, 19.05%, 19.05%, 23.81%, 19.05%),
    align: (left,left,left,center,left,),
    table.header([Source Model], [Target Model], [Exchange
      Variable], [Symbol / Units], [Physical Coupling Effect],),
    table.hline(),
    [#strong[WRF]], [#strong[CROCO]], [Surface Stress & Heat
    Flux], [$tau\,upright("shflux")$
    ($upright("N/m")^2\,upright("W/m")^2$)], [Drives Ekman currents &
    water column thermal structure],
    [#strong[CROCO]], [#strong[WRF]], [Sea Surface
    Temperature], [$upright("SST")$
    ($""^compose upright("C")$)], [Modulates atmospheric boundary layer
    stability & flux coefficients],
    [#strong[SWAN]], [#strong[CROCO]], [Wave Height, Period &
    $U_(b o t)$], [$H_s\,T_p\,U_(b o t)$
    ($upright("m")\,upright("s")\,upright("m/s")$)], [Drives wave
    radiation stresses & bottom friction enhancement],
    [#strong[CROCO]], [#strong[SWAN]], [Currents & Sea Surface
    Height], [$u\,v\,zeta$ ($upright("m/s")\,upright("m")$)], [Causes
    Doppler shift, wave refraction, & depth-induced breaking],
    [#strong[SWAN]], [#strong[WRF]], [Surface Roughness Length], [$z_0$
    ($upright("m")$)], [Adjusts atmospheric surface drag based on real
    wave state],
    [#strong[WRF]], [#strong[SWAN]], [$10 upright(" m")$ Surface Wind
    Vectors], [$U_10\,V_10$ ($upright("m/s")$)], [Governs spectral wave
    energy generation ($S_(i n)$)],
  )]
  , kind: table
  )
