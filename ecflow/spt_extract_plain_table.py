#################################################################
#
# File: spt_extract_plain_table.py
# Author(s):
#   Michael Souffront,
#   Wade Roberts,
#   Spencer McDonald,
#   Josh Ogden,
#   Riley Hales
# Date: 03/07/2018
# Last Updated: 05/28/2020
# Purpose: Calculate basic statistics for GloFAS-RAPID files and
#          extract them to a summary table; interpolate forecast
#          values for time steps other than 3 hrs
# Requirements: NCO, netCDF4, pandas
#
#################################################################

import datetime as dt
import logging
import multiprocessing as mp
import os
import subprocess as sp
import sys
from glob import glob

import netCDF4 as nc
import pandas as pd
from scipy.interpolate import pchip


def extract_summary_table(workspace):
    # calls NCO's nces function to calculate ensemble statistics for the max, mean, and min
    nces_exec = str(sys.argv[3])
    for stat in ['max', 'avg', 'min']:
        findstr = 'find {0} -name "Qout*.nc"'.format(workspace)
        filename = os.path.join(workspace, 'nces.{0}.nc'.format(stat))
        ncesstr = "{0} -O --op_typ={1} {2}".format(nces_exec, stat, filename)
        args = ' | '.join([findstr, ncesstr])
        sp.call(args, shell=True)

    # creates list with the stat netcdf files created in the previous step
    nclist = []
    for file in os.listdir(workspace):
        if file.startswith("nces"):
            nclist.append(os.path.join(workspace, file))

    # creates file name for the csv file
    date_string = os.path.split(workspace)[1].replace('.', '')
    full_name = os.path.split(os.path.split(workspace)[0])[1]
    file_name = 'summary_table_{0}_{1}.csv'.format(full_name, date_string)
    static_path = str(sys.argv[5])

    # creating pandas dataframe with return periods
    era_type = str(sys.argv[4])
    logging.info(f'Workspace {workspace}')
    rp_path = glob(os.path.join(static_path, era_type, os.path.basename(os.path.split(workspace)[0]),
                                f'*return_periods_{era_type}*.nc*'))[0]
    logging.info(f'Return Period Path {rp_path}')
    rp_ncfile = nc.Dataset(rp_path, 'r')

    # extract values
    rp_comid = rp_ncfile.variables['rivid'][:]
    data = {
        'return_2': rp_ncfile.variables['return_period_2'][:],
        'return_5': rp_ncfile.variables['return_period_5'][:],
        'return_10': rp_ncfile.variables['return_period_10'][:],
        'return_25': rp_ncfile.variables['return_period_25'][:],
        'return_50': rp_ncfile.variables['return_period_50'][:],
        'return_100': rp_ncfile.variables['return_period_100'][:]
    }

    #  creates dataframe
    rp_df = pd.DataFrame(data, index=rp_comid)

    # creates a csv file to store statistics
    try:
        # writes header
        # f.write('comid,timestamp,max,mean,color,thickness,ret_per\n')

        # extracts forecast COMIDS and formatted dates into lists
        comids = nc.Dataset(nclist[0], 'r').variables['rivid'][:].tolist()
        rawdates = nc.Dataset(nclist[0], 'r').variables['time'][:].tolist()
        dates = []
        for date in rawdates:
            dates.append(dt.datetime.utcfromtimestamp(date).strftime("%m/%d/%y %H:%M"))
        # creates a time series of 3H intervals for interpolation,
        # coerces a copy to appropriate type for inserting to file
        interp_x = pd.date_range(
            start=dates[0],
            end=dates[-1],
            freq='3H'
        )
        interp_x_strings = interp_x.strftime("%m/%d/%y %H:%M")
        new_dates = list(interp_x_strings)
        dt_dates = pd.to_datetime(dates)

        # creates empty lists with forecast stats
        maxlist = []
        meanlist = []

        # loops through the stat netcdf files to populate lists created above
        for ncfile in sorted(nclist):
            res = nc.Dataset(ncfile, 'r')

            # loops through COMIDs with netcdf files, adds maxes and means
            # originally took a slice of the first 49 to only include high res,
            # but now extracts the whole forecast so the interpolator can fill
            # in the gaps.
            for index, comid in enumerate(comids):
                if 'max' in ncfile:
                    maxlist.append(res.variables['Qout'][index, :].round(2).tolist())
                elif 'avg' in ncfile:
                    meanlist.append(res.variables['Qout'][index, :].round(2).tolist())
        # loops through the lists of max lists and mean lists to interpolate using the dates as x values

        columns = ['comid', 'timestamp', 'max', 'mean', 'color', 'thickness', 'ret_per']
        summary_table_df = pd.DataFrame(columns=columns)
        for index, comid, date, maxes, means in enumerate(zip(comids, new_dates, maxlist, meanlist)):
            # interpolate maxes and means
            max_interpolator = pchip(dt_dates, maxes)
            mean_interpolator = pchip(dt_dates, means)
            int_max = max_interpolator(interp_x)
            int_mean = mean_interpolator(interp_x)
            # loop for creating color, thickness, and return period columns
            colors = []
            thicknesses = []
            ret_pers = []
            for f_mean in int_mean:
                # define reach color based on return periods
                if f_mean > rp_df.loc[comid, 'return_50']:
                    color = 'purple'
                elif f_mean > rp_df.loc[comid, 'return_10']:
                    color = 'red'
                elif f_mean > rp_df.loc[comid, 'return_2']:
                    color = 'yellow'
                else:
                    color = 'blue'

                colors.append(color)

                # define reach thickness based on flow magnitude
                if f_mean < 20:
                    thickness = '1'
                elif 20 <= f_mean < 250:
                    thickness = '2'
                elif 250 <= f_mean < 1500:
                    thickness = '3'
                elif 1500 <= f_mean < 10000:
                    thickness = '4'
                elif 10000 <= f_mean < 30000:
                    thickness = '5'
                else:
                    thickness = '6'

                thicknesses.append(thickness)

                # define return period exceeded by the mean forecast
                if f_mean > rp_df.loc[comid, 'return_100']:
                    ret_per = '100'
                elif f_mean > rp_df.loc[comid, 'return_50']:
                    ret_per = '50'
                elif f_mean > rp_df.loc[comid, 'return_25']:
                    ret_per = '25'
                elif f_mean > rp_df.loc[comid, 'return_10']:
                    ret_per = '10'
                elif f_mean > rp_df.loc[comid, 'return_5']:
                    ret_per = '5'
                elif f_mean > rp_df.loc[comid, 'return_2']:
                    ret_per = '2'
                else:
                    ret_per = '0'

                ret_pers.append(ret_per)

            # create the dataframe for the site and concatenate onto
            site_summary = pd.DataFrame(
                data={
                    columns[0]: pd.Series([comid for comid in range(len(new_dates))]),
                    columns[1]: pd.Series(new_dates),
                    columns[2]: pd.Series(int_max).round(2),
                    columns[3]: pd.Series(int_mean).round(2),
                    columns[4]: pd.Series(colors),
                    columns[5]: pd.Series(thicknesses),
                    columns[6]: pd.Series(ret_pers)
                }
            )
            summary_table_df = pd.concat([summary_table_df, site_summary], ignore_index=True)
        # write to csv
        summary_table_df.to_csv(os.path.join(workspace, file_name), index=False)

        return 'Stat Success'
    except Exception as e:
        logging.debug(e)


# runs function on file execution
if __name__ == "__main__":
    """
    Arguments:

    1. Absolute path to the rapid-io/output directory ???
    2. Path to the logging file (not used)
    3. NCO command to compute ensemble stats ???
    4. era_type: == 'era_5' ???
    5. static_path == absolute path to the root directory with all
        return period files. The next level after this directory
        should be the different era types.

    Example Usage

        python spt_extract_plain_table.py arg1 arg2 arg3 arg4 arg5

        python spt_extract_plain_table.py /path/to/rapid-io/output blank blank era_5 /path/to/returnperiods/root

    """

    logging.basicConfig(filename=str(sys.argv[2]), level=logging.DEBUG)
    logging.basicConfig(level=logging.DEBUG)

    # output directory
    workdir = str(sys.argv[1])
    # list of watersheds
    watersheds = [os.path.join(workdir, d) for d in os.listdir(workdir) if os.path.isdir(os.path.join(workdir, d))]
    logging.debug(watersheds)
    dates = []
    exclude_list = []
    for i in range(len(watersheds)):
        for d in os.listdir(watersheds[i]):
            if not any(excluded in watersheds[i] for excluded in exclude_list) and os.path.isdir(
                    os.path.join(watersheds[i], d)):
                dates.append(os.path.join(watersheds[i], d))
                # logging.info(os.path.join(watersheds[i], d))
    logging.debug(dates)
    pool = mp.Pool()
    results = pool.map(extract_summary_table, dates)

    pool.close()
    pool.join()
    logging.debug('Finished')