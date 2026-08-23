#!/usr/bin/env python3
import os
import pathlib

def main():
    lm = int(os.environ.get("PREDSEA_CROCO_LM", "499"))
    mm = int(os.environ.get("PREDSEA_CROCO_MM", "399"))
    vertical_levels = int(os.environ.get("PREDSEA_CROCO_N", "32"))
    np_xi = int(os.environ.get("PREDSEA_CROCO_NP_XI", "4"))
    np_eta = int(os.environ.get("PREDSEA_CROCO_NP_ETA", "4"))

    if min(lm, mm, vertical_levels, np_xi, np_eta) <= 0:
        raise ValueError("CROCO compile-time dimensions and MPI decomposition must be positive")

    build_dir = pathlib.Path("tmp/croco_build")
    src_cppdefs = build_dir / "croco_src/OCEAN/cppdefs.h"
    dst_cppdefs = build_dir / "cppdefs.h"
    src_param = build_dir / "croco_src/OCEAN/param.h"
    dst_param = build_dir / "param.h"
    src_bulk_flux = build_dir / "croco_src/OCEAN/bulk_flux.F"

    if not src_cppdefs.exists() or not src_param.exists():
        print("❌ Error: CROCO source files not found under tmp/croco_build/croco_src/OCEAN/")
        return 1

    total_ranks = np_xi * np_eta

    # 1. Patch cppdefs.h
    print(f"📝 Patching cppdefs.h (MPI ranks: {total_ranks})...")
    cppdefs_content = src_cppdefs.read_text()

    # Define BALEARIC_1KM and undefine BENGUELA_LR
    cppdefs_content = cppdefs_content.replace(
        "# define BENGUELA_LR",
        "# undef BENGUELA_LR\n# define BALEARIC_1KM"
    )

    if total_ranks > 1:
        cppdefs_content = cppdefs_content.replace(
            "# undef  MPI",
            "# define MPI"
        )
    else:
        cppdefs_content = cppdefs_content.replace(
            "# undef  MPI",
            "# undef MPI"
        )

    # Enable CLIMATOLOGY boundaries and nudging
    cppdefs_content = cppdefs_content.replace(
        "# undef CLIMATOLOGY",
        "# define CLIMATOLOGY"
    )

    # Use real gridded WRF bulk forcing. Explicitly disable the analytical
    # zero-flux fallback used by the historical compile-only prototype.
    cppdefs_content += "\n\n/* BALEARIC_1KM Specific Overrides */\n#ifdef BALEARIC_1KM\n# define MASKING\n# define BULK_FLUX\n# define BULK_LW\n# define DIURNAL_SRFLUX\n# define QCORRECTION\n# define SOLAR_PENETRATION\n# define WTYPE 1\n# define LMD_MIXING\n# ifdef LMD_MIXING\n#  define LMD_SKPP\n#  define LMD_BKPP\n#  define LMD_RIMIX\n#  define LMD_CONVEC\n#  define LMD_NONLOCAL\n# endif\n# define SPLINES_VDIFF\n# define SPLINES_VDIFF_TRACER\n# define UV_LOGDRAG\n# define SPONGE_GRID\n# undef ONLINE\n# undef MERRA_AEROSOL\n# undef ANA_SMFLUX\n# undef ANA_STFLUX\n# undef ANA_SSFLUX\n# define FRC_BRY\n# define Z_FRC_BRY\n# define M2_FRC_BRY\n# define M3_FRC_BRY\n# define T_FRC_BRY\n#endif\n"

    dst_cppdefs.write_text(cppdefs_content)
    print("✅ Patched cppdefs.h successfully!")

    # 2. Patch param.h
    print(f"📝 Patching param.h (NP_XI={np_xi}, NP_ETA={np_eta})...")
    param_content = src_param.read_text()

    # Inject BALEARIC_1KM dimension parameters
    param_content = param_content.replace(
        "#  elif defined GIBRALTAR_VHR5",
        "#  elif defined BALEARIC_1KM\n"
        f"       parameter (LLm0={lm}, MMm0={mm},  N={vertical_levels})\n"
        "#  elif defined GIBRALTAR_VHR5"
    )

    # Set MPI subdivision grid for BALEARIC_1KM
    param_content = param_content.replace(
        "      parameter (NP_XI=1,  NP_ETA=4,  NNODES=NP_XI*NP_ETA)",
        f"# if defined BALEARIC_1KM\n      parameter (NP_XI={np_xi},  NP_ETA={np_eta},  NNODES=NP_XI*NP_ETA)\n# else\n      parameter (NP_XI={np_xi},  NP_ETA={np_eta},  NNODES=NP_XI*NP_ETA)\n# endif"
    )

    dst_param.write_text(param_content)
    print("✅ Patched param.h successfully!")

    # 3. Patch bulk_flux.F
    if src_bulk_flux.exists():
        print("📝 Patching bulk_flux.F heat flux sign convention...")
        bulk_content = src_bulk_flux.read_text()
        old_target = "          hflat=-hflat*rho0i*cpi\n          hfsen=-hfsen*rho0i*cpi"
        new_replacement = (
            "          ! --- FIXED SIGN CONVENTION FOR BULK FLUXES ---\n"
            "          ! 1. Latent Heat Flux: Evaporation MUST remove energy from ocean (< 0)\n"
            "          hflat=-ABS(hflat)*rho0i*cpi\n"
            "          ! 2. Sensible Heat Flux: Conduction when SST > T_air MUST remove energy from ocean (< 0)\n"
            "          IF (TseaC .gt. TairC) THEN\n"
            "            hfsen=-ABS(hfsen)*rho0i*cpi\n"
            "          ELSE\n"
            "            hfsen=-hfsen*rho0i*cpi\n"
            "          ENDIF"
        )
        if old_target in bulk_content:
            bulk_content = bulk_content.replace(old_target, new_replacement)
            src_bulk_flux.write_text(bulk_content)
            print("✅ Patched bulk_flux.F successfully!")
        else:
            print("⚠️ Warning: Target pattern in bulk_flux.F not found; checking if already patched.")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
