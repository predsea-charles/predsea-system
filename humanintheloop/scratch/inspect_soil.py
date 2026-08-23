import eccodes
import requests
from ecmwf.opendata import Client
import os

def inspect_grib(filename):
    print(f"Inspecting {filename}...")
    with open(filename, 'rb') as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            
            shortName = eccodes.codes_get(gid, 'shortName')
            typeOfLevel = eccodes.codes_get(gid, 'typeOfLevel')
            level = eccodes.codes_get(gid, 'level')
            discipline = eccodes.codes_get(gid, 'discipline')
            parameterCategory = eccodes.codes_get(gid, 'parameterCategory')
            parameterNumber = eccodes.codes_get(gid, 'parameterNumber')
            scaledValueOfFirstFixedSurface = eccodes.codes_get(gid, 'scaledValueOfFirstFixedSurface')
            scaledValueOfSecondFixedSurface = eccodes.codes_get(gid, 'scaledValueOfSecondFixedSurface')
            
            print(f"Variable: {shortName}")
            print(f"  typeOfLevel: {typeOfLevel}")
            print(f"  level: {level}")
            print(f"  discipline: {discipline}")
            print(f"  parameterCategory: {parameterCategory}")
            print(f"  parameterNumber: {parameterNumber}")
            print(f"  FirstFixedSurface: {scaledValueOfFirstFixedSurface}")
            print(f"  SecondFixedSurface: {scaledValueOfSecondFixedSurface}")
            
            eccodes.codes_release(gid)

client = Client(source="ecmwf")
# Just download one soil message
client.retrieve(
    date=-1,
    time=0,
    step=0,
    stream="oper",
    type="fc",
    levtype="sol",
    param="sot",
    levelist=1,
    target="test_soil.grib2"
)

inspect_grib("test_soil.grib2")
