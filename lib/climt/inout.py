import os
from numpy import *
from __version__ import __version__
import time

if 'climt_lite' in __file__:
    Lite = True
else:
    Lite = False

try:
    from netCDF4 import Dataset as open_file
    got_netcdf = True
    netcdf_interface = 'netCDF4'
except:
    got_netcdf = False

if not got_netcdf:
    try:
        from Scientific.IO.NetCDF import NetCDFFile as open_file
        got_netcdf = True
        netcdf_interface = 'Scientific'
    except:
        got_netcdf = False

if not got_netcdf:
    try:
        from PyNGL.Nio import open_file 
        got_netcdf = True
        netcdf_interface = 'PyNGL'
    except:
        got_netcdf = False

if got_netcdf:
    print 'Using %s interface for IO' % netcdf_interface
else:
    if not Lite: print '\n ++++ CliMT: WARNING: NetCDF interface ' \
          +'could not be loaded, so no file input or output !\n' 

from state import KnownFields

class IO:
    """
    """
    def __init__(self, component, **kwargs):
        """
        """
        if not got_netcdf:
            self.doing_output = False
            self.appending = False
            return

        self.restart_filename = None
        self.output_filename = None
        self.output_fields = None
        self.output_frequency = 86400.

        self.doing_output = False
        self.appending = False

        # Inititalize output time index
        self.OutputTimeIndex = 0

        # Restart file name
        if 'RestartFile' in kwargs:
            self.restart_filename = kwargs['RestartFile']

        # Output file name
        if 'OutputFile' in kwargs:
            self.output_filename = kwargs['OutputFile']

        # If no fields are specified, ALL fields in State will
        # be output (see writeOuput)
        if 'OutputFields' in kwargs:
            self.output_fields = kwargs['OutputFields']

        # If no output frequency specifed, output once daily
        if 'OutputFreq' in kwargs:
            self.output_frequency = kwargs['OutputFreq']

        # Decide if we're doing output
        if  self.output_filename is not None:
            self.doing_output = True
        else:
            # TODO: This is bad control flow. Should be cleaned up.
            return

        # Decide if we're appending output to restart file
        if self.output_filename is not None and \
           self.output_filename == self.restart_filename:
            self.appending = True
        else:
            self.appending = False

        # Set of all fields in State
        self.all_fields = \
              list(set(component.Required).union(component.Diagnostic).union(component.Prognostic))

        # Check that OutputFieldNames is a subset of AllFields
        if self.output_fields is None:
            odd_fields = []
        else:
            odd_fields = list(set(self.output_fields).difference(self.all_fields))
        if len(odd_fields) > 0: raise \
           '\n +++ CliMT.IO.init: Output fields %s not recognized\n' % str(list(odd_fields))
        
        # Inititalize output time index
        self.output_time_index = 0


    def readRestart(self, FieldNames, ParamNames, kwargs):
        """
        Reads required parameters and fields from restart file.
        """        
        if not got_netcdf: return kwargs

        # Open file
        try:
            File = open_file(self.restart_filename, 'r')
        except IOError:  
            raise IOError, \
            '\n ++++ CliMT.IO.readRestart: Restart file %s not found or unreadable\n' \
            % self.restart_filename
            
        # Read elapsed time
        if 'ElapsedTime' not in kwargs:
            kwargs['ElapsedTime'] = File.variables['time'][-1]*86400.

       # Read parameters (they are stored as global attribs)
        for Name in ParamNames:
            try:
                exec('if Name not in kwargs: kwargs["%s"] = File.%s'%(Name,Name))
            except:
                print '\n ++++ CliMT.readRestart: Parameter %s ' % Name + \
                'not found in restart file, using default or supplied value\n'
            
        # Read grid
        if 'lev' not in kwargs: kwargs['lev'] = File.variables['lev'][:][::-1].astype('d')
        for Name in ['lat','lon']:
            if Name not in kwargs: kwargs[Name] = File.variables[Name][:].astype('d')
                        
        # Read variables 
        for Name in FieldNames:
            if Name not in kwargs:
                try:
                    kwargs[Name] = File.variables[Name][-1].astype('d')
                    if KnownFields[Name][2] == '3D': kwargs[Name] = kwargs[Name][::-1]
                except:
                    print '\n ++++ CliMT.readRestart: Field %s ' % Name + \
                          'not found in restart file, using default or supplied value\n'

         # If we're appending to restart file, shift time index forward
        if self.appending: self.output_time_index = len(File.variables['time'][:])
        
        # Close file and return values
        File.close()
        print ' Read from restart file %s\n' % self.restart_filename
        return kwargs

    def createOutputFile(self, State, Params):
        """
        Creates output file with all fields in State
        """
        # If we're not doing output or we're appending to restart file, skip creation
        if not got_netcdf or not self.doing_output or self.appending: return

        # Create file
        os.system('rm -f %s' % self.output_filename)
        if netcdf_interface == 'netCDF4':
            File = open_file(self.output_filename, 'w', format='NETCDF3_CLASSIC')
        else:
            File = open_file(self.output_filename, 'w')
        # rename methods
        if netcdf_interface in  ['netCDF4', 'Scientific']:
            createDimension = File.createDimension
            createVariable  = File.createVariable
        elif netcdf_interface == 'PyNGL':
            createDimension = File.create_dimension
            createVariable  = File.create_variable

        # Define some global attribs
        File.Conventions='COARDS'
        File.CliMTVersion = __version__
        File.RunStartDate = time.ctime()
        File.NetCDFInterface = netcdf_interface
        if self.restart_filename is not None:
            File.RestartFile = self.restart_filename

        # Store parameters as global attribs
        for Name in Params:
            exec('File.%s = Params["%s"]'%(Name,Name))

        # Create dimensions and axes. Time is record dimension and gets special treatement
        createDimension('time',None)
        var = createVariable('time','d',('time',))
        var.long_name = 'time'
        var.units     = 'days'
        createDimension('lev',len(State.Grid['lev']))
        var = createVariable('lev','d',('lev',))
        var.long_name = 'level'
        var.units     = 'mb'
        var.depth     = 'true'
        var[:] = State.Grid['lev']
        for key in ['lat','lon']:
            createDimension(key,len(State.Grid[key]))
            var = createVariable(key,'d',(key,))
            var.long_name = State.Grid.long_name[key]
            var.units     = State.Grid.units[key]
            var[:]        = State.Grid[key]
        # Create output fields
        axes2D = ('time','lon','lat')
        axes3D = ('time','lon','lat','lev')
        for key in self.all_fields:
            exec('axes = axes%s' % KnownFields[key][2])
            var = createVariable(key, 'f', axes)
            var.long_name = KnownFields[key][0]
            var.units     = KnownFields[key][1]
        # Close file
        File.close()

    def writeOutput(self, Params, State):
        """
        """            
        if not got_netcdf or not self.doing_output:
            # TODO: This should probably raise an error
            return

        # Open file
        File = open_file(self.output_filename, 'a')

        # Decide what we're going to output
        if State.ElapsedTime == 0. or self.OutputFieldNames == None:
            # TODO
            #For now, until we figure this out
            #OutputFieldNames = self.all_fields
            OutputFieldNames = self.output_fields
        else:
            OutputFieldNames = self.output_fields

        # Write variables (as 'f' to reduce file size)
        File.variables['time'][self.output_time_index] = State.ElapsedTime / 86400.
        nlev = State.Grid['nlev']
        for key in OutputFieldNames:
            if KnownFields[key][2] == '2D':
                out = State[key].copy()
                File.variables[key][self.output_time_index, :, :] = out[:, :].astype('f')
            if KnownFields[key][2] == '3D':
                out = State[key].copy()
                out = out[:,:,nlev-1::-1]
                File.variables[key][self.output_time_index,:,:,:] = out[:,:,:].astype('f')

        # Write time
        File.variables['time'][self.output_time_index] = State.ElapsedTime / 86400.

        # Write calday
        File.calday = Params['calday']
        
        # Advance time index
        self.output_time_index += 1

        # Close file
        File.close()
        print ' Wrote to file %s, time=%10.5f days' % \
              (self.output_filename, State.ElapsedTime / 86400.)
