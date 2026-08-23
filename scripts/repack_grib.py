import eccodes
import sys
import os

def repack_grib(input_file, output_file):
    print(f"Repacking {input_file} to {output_file}...")
    count = 0
    with open(input_file, 'rb') as f_in, open(output_file, 'wb') as f_out:
        while True:
            gid = eccodes.codes_grib_new_from_file(f_in)
            if gid is None:
                break
            
            # Check current packing type
            try:
                packing_type = eccodes.codes_get(gid, 'packingType')
                # Only repack if it's CCSDS
                if packing_type == 'grid_ccsds':
                    eccodes.codes_set(gid, 'packingType', 'grid_simple')
            except Exception as e:
                print(f"Error checking/setting packingType: {e}")
            
            eccodes.codes_write(gid, f_out)
            eccodes.codes_release(gid)
            count += 1
            if count % 100 == 0:
                print(f"Processed {count} messages...")
    
    print(f"Finished repacking {count} messages.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python repack_grib.py input.grib2 output.grib2")
        sys.exit(1)
    repack_grib(sys.argv[1], sys.argv[2])
