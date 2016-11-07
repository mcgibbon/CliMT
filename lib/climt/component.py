#!/usr/bin/env python

from numpy import *
from parameters import Parameters
from state      import State, KnownFields
from plot       import Monitor, Plot
from io         import IO
from utils      import squeeze
from _grid      import get_nlev, get_nlat, get_nlon

class Component:
    """
    Abstract class defining methods inherited by all CliMT components.
    """

    name = ''

    def __init__(self, **kwargs):

        # Initialize self.Fixed (subset of self.Prognostic which will NOT be time-marched)
        if 'Fixed' in kwargs:
            self.Fixed = kwargs.pop('Fixed')
        else:
            self.Fixed = []

        # Initialize I/O
        self.io = IO(self, **kwargs)

        # Get values from restart file, if available
        if 'RestartFile' in kwargs:
            parameter_names = Parameters().value.keys()
            field_names = self.Required
            kwargs = self.io.readRestart(field_names, parameter_names, kwargs)

        # Initialize scalar parameters
        self.parameters = Parameters(**kwargs)

        # Frequency with which compute() will be executed
        if 'UpdateFreq' in kwargs:
            self.update_frequency = kwargs.pop('UpdateFreq')
        else:
            self.update_frequency = self.parameters['dt']

        # Initialize State
        self.state = State(self, **kwargs)
        self.grid = self.state.Grid

        # Dictionary to hold increments on prognos fields
        self.Inc = {}

        # Initialize diagnostics
        self.compute(ForcedCompute=True)

        # Create output file
        self.io.createOutputFile(self.state, self.parameters.value)

        # Write out initial state
        if not self.io.Appending: self.write()

        # Initialize plotting facilities
        self.plot = Plot()

        # Initialize runtime monitor
        self.monitor = Monitor(self, **kwargs)

        # Notify user of unused input quantities
        self._check_unused(kwargs)

        # Set some redundant attributes (mainly for backward compatibility)
        self.nlon = self.grid['nlon']
        self.nlat = self.grid['nlat']
        self.nlev = self.grid['nlev']
        try:
            self.o3 = self.state['o3']
        except:
            pass

    def compute(self, ForcedCompute=False):
        """
        Updates component's diagnostics and increments
        """
        # See if it's time for an update; if not, skip rest
        if not ForcedCompute:
            freq = self.update_frequency
            time = self.state.ElapsedTime
            if int(time/freq) == int((time-self['dt'])/freq): return

        # Set up union of State, Grid and Params
        Input = {}
        for dic in [self.state.Now, self.grid.value, self.parameters.value]: Input.update(dic)
        Input['UpdateFreq'] = self.update_frequency

        # For implicit time stepping, replace current time level with previous (old) time level
        if self.SteppingScheme == 'implicit': Input.update(self.state.Old)

        # For semimplicit time stepping, append previous (old) time level to Input dict
        if self.SteppingScheme == 'semi-implicit':
            for key in self.Prognostic: Input[key+'old'] = self.state.Old[key]

        # List of arguments to be passed to extension
        args = [ Input[key] for key in self.ToExtension ]

        # Call extension and build dictionary of ouputs
        OutputValues = self.driver(*args)
        if len(self.FromExtension) == 1: Output = {self.FromExtension[0]: OutputValues}
        else:                            Output = dict( zip(self.FromExtension, OutputValues ) )

        # Extract increments from Output
        for key in self.Prognostic:
            self.Inc[key] = Output.pop(key+'inc')

        # Remove increments of Fixed variables
        for key in self.Fixed:
            if key in self.Inc: self.Inc.pop(key)
            if key in Output: Output.pop(key)

        # Update State
        self.state.update(Output)
        for key in Output: exec('self.'+key+'=Output[key]')

        # No further need for input dictionary
        del(Input)

    def step(self, RunLength=1, Inc={}):
        """
        Advances component one timestep and writes to output file if necessary.
        Inc is an externally-specified set of increments added to the internally-computed
        increments at each time step.
        """

        # If RunLength is integer, interpret as number of time steps
        if type(RunLength) is type(1):
            NSteps = RunLength

        # If RunLength is float, interpret as length of run in seconds
        if type(RunLength) is type(1.):
            NSteps = int(RunLength/self['dt'])

        for i in range(NSteps):
            # Add external increments
            for key in Inc.keys():
                if key in self.Inc.keys():
                    self.Inc[key] += Inc[key]
                else:
                    self.Inc[key] = Inc[key]

            # Avance prognostics 1 time step
            self.state.advance(self)

            # Bring diagnostics and increments up to date
            self.compute()

            # Bring calendar up to date
            self['calday'] += self['dt']/self['lod']
            if self['calday'] > self['daysperyear']:
                self['calday'] -= self['daysperyear']

            # Write to file, if it's time to
            dt   = self.parameters['dt']
            time = self.state.ElapsedTime
            freq = self.io.OutputFreq
            if int(time/freq) != int((time-dt)/freq): self.write()

            # Refresh monitor, if it's time to
            if self.monitor.Monitoring:
                freq = self.monitor.MonitorFreq
                if int(time/freq) != int((time-dt)/freq): self.monitor.refresh(self)

    def __call__(self,**kwargs):
        """
        # Provides a simple interface to extension, useful e.g. for diagnostics.
        """
        # Re-initialize parameters, grid and state
        self.parameters  = Parameters(**kwargs)
        self.state = State(self, **kwargs)
        self.grid = self.state.Grid
        # Bring diagnostics up to date
        self.compute()

    def write(self):
        """
        Invokes write method of IO instance to write out current State
        """
        self.io.writeOutput(self.parameters, self.state)

    def open(self, OutputFileName='CliMT.nc'):
        """
        """
        if self.io.OutputFileName == OutputFileName:
            print '\n +++ ClimT.Io: File %s is currently open for output'% OutputFileName
            return
        else:
            print 'Opening %s for output'% OutputFileName
            self.io.OutputFileName = OutputFileName
            self.io.DoingOutput = True
            self.io.Appending = False
            self.io.OutputTimeIndex = 0
            self.io.createOutputFile(self.state, self.parameters)

    def plot(self, *FieldKeys):
        self.plot(self, *FieldKeys)

    def setFigure(self, FigureNumber=None):
        self.plot.setFigure(FigureNumber)

    def closeFigure(self, FigureNumber=None):
        self.plot.closeFigure(FigureNumber)

    def usage(self):
        print self.__doc__

    def report(self):
        print 'CliMT component:\n    %s' % self.name
        keys = self.state.keys()
        keys1 = []
        for i in range(len(keys)):
            if   keys[i] in self.Prognostic: keys1.append('%12s   %s' % (keys[i],'(prognostic)'))
        for i in range(len(keys)):
            if keys[i] in self.Diagnostic: keys1.append('%12s   %s' % (keys[i],'(diagnostic)'))
        for i in range(len(keys)):
            if keys[i] not in self.Prognostic and keys[i] not in self.Diagnostic:
                                           keys1.append('%12s   %s' % (keys[i],'(Fixed)'))
        print 'State variables:\n %s' % '\n '.join( keys1 )

    def _check_unused(self, kwargs):
        '''
        Notify of unused input quantities.
        '''
        unused = []
        io_keys = ['RestartFile','OutputFile','OutputFreq','OutputFields','ElapsedTime']
        monitor_keys = ['MonitorFields','MonitorFreq']
        for key in kwargs:
            if key not in self.parameters  \
            and key not in self.grid   \
            and key not in KnownFields \
            and key not in io_keys \
            and key not in monitor_keys:
                unused.append(key)

        if len(unused) > 0:
           if len(unused) == 1: suffix = 'y'
           else              : suffix = 'ies'
           print '\n ++++ CliMT.'+self.name + '.initialize: WARNING: Input quantit%s %s not used.\n' \
                                              % (suffix,str(list(unused)))

    def _getShape3D(self, **kwargs):
        '''
        Returns shape of 3D arrays to be passed to extension.
        '''
        return (self._getAxisLength('lev', **kwargs),
                self._getAxisLength('lat', **kwargs),
                self._getAxisLength('lon', **kwargs))


    def _getAxisLength(self, AxisName, **kwargs):
        '''
        Returns length of axis.
        '''
        # Check input
        assert AxisName in ['lev','lat','lon'], \
               '\n\n ++++ CliMT.{}: Axis name must be one of "lon", "lat", "lev"'.format(self.name)

        # See if axis was supplied in input
        n = None
        if AxisName in kwargs:
            if ndim(array(kwargs[AxisName])) == 0:
                n = 1
            else:
                assert ndim(array(kwargs[AxisName])) == 1, \
                    '\n\n ++++ CliMT.%s.init: input %s must be rank 1' % (self.name, AxisName)
                n = len(array(kwargs[AxisName]))

        # If not, see if some field was supplied
        else:
            for key in kwargs:
                if key in KnownFields:
                    if KnownFields[key][2] == '2D' and AxisName != 'lev':
                        i = ['lat','lon'].index(AxisName)
                        try:    n = array(kwargs[key]).shape[i]
                        except: n = 1
                    elif KnownFields[key][2] == '3D':
                        i = ['lev','lat','lon'].index(AxisName)
                        try:    n = array(kwargs[key]).shape[i]
                        except: n = 1

        # Last resort: get dimensions set in Makefile
        if n is None: exec('n = get_n%s()' % AxisName)

        # Check if extension enforces axis dimension, ensure consistency
        try:
            exec('n_ext = self.Extension.get_n%s()' % AxisName)
        except:
            n_ext = n
        assert n_ext == n, \
            '\n\n ++++ CliMT.%s.init: input %s has dimension %i but extension requires %i'% \
            (self.name, AxisName, n, n_ext)

        return n

    # Returns requested quantity from Params, Grid or State
    def __getitem__(self, key):
        for obj in [self.parameters, self.grid, self.state]:
            if key in obj:
                if type(obj[key]) is type('string'): return obj[key]
                else: return squeeze(obj[key])
        raise IndexError,'\n\n CliMT.State: %s not in Params, Grid or State' % str(key)

    # Sets requested quantity in Params, Grid or State
    def __setitem__(self, key, value):
        if key in self.parameters:
            self.parameters[key] = value
            return
        if key in self.grid:
            self.grid[key] = value
            return
        elif key in self.state and KnownFields[key][2] == '2D':
            self.state[key]=reshape(value, self.grid.Shape3D[1:3])
            return
        elif key in self.state and KnownFields[key][2] == '3D':
            self.state[key]=reshape(value, self.grid.Shape3D)
            return
        else:
            raise IndexError, '\n\n CliMT.State: %s not in Params, Grid or State' % str(key)
