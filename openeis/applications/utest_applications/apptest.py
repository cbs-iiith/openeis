"""
Module for testing applications.
"""

import datetime
import csv
import os
import math
import tempfile

from django.test import TestCase
from django.utils.timezone import utc
from subprocess import call
from configparser import ConfigParser

from openeis.applications import get_algorithm_class
from openeis.projects.storage.db_output import DatabaseOutputFile
from openeis.projects.storage.db_input import DatabaseInput
from openeis.projects import models


class AppTestBase(TestCase):


    # Taken directly from runapplication command.
    def run_application(self, config_file, output_dir):
        """
        Runs the application with a given configuration file.
        Parameters:
            - config_file: configuration files passed into runapplication
            - output_dir: directory for output files
        Returns:
            - actual_output, dictionary, maps table name to file name of run results
        """
        config = ConfigParser()
        # Read the file
        config.read(config_file)
        # Grab application name
        application = config['global_settings']['application']
        # Get which application we need
        klass = get_algorithm_class(application)
        # Check which data set we're using
        dataset_id = int(config['global_settings']['dataset_id'])
        dataset = models.SensorIngest.objects.get(pk=dataset_id)

        kwargs = {}
        if config.has_section('application_config'):
            for arg, str_val in config['application_config'].items():
                kwargs[arg] = eval(str_val)

        topic_map = {}
        # Grab the inputs to be used with the application.
        inputs = config['inputs']
        for group, topics in inputs.items():
            topic_map[group] = topics.split()

        now = datetime.datetime.utcnow().replace(tzinfo=utc)
        analysis = models.Analysis(
            added=now, started=now, status="running",
            dataset=dataset, application=application,
            configuration={
                'parameters': kwargs,
                'inputs': topic_map
                },
            name='cli: {}, dataset {}'.format(application, dataset_id)
            )
        analysis.save()

        db_input = DatabaseInput(dataset.map.id, topic_map, dataset_id)

        output_format = klass.output_format(db_input)
        file_output = DatabaseOutputFile(analysis, output_format)

        app = klass(db_input, file_output, **kwargs)
        # Execute the application
        app.run_application()

        # Retrieve the map of tables to output csvs from the application
        actual_output = {}
        for tableName in app.out.file_table_map.keys():
            actual_output[tableName] = app.out.file_table_map[tableName].name

        return actual_output


    def _call_runapplication(self, tables, config_file, output_dir):
        """
        Runs the application, checks if a file was outputted from the
        application.  It can tolerate more than one output file for an
        application run.

        Parameters:
            - tables: application names as a list
            - config_file: configuration file to pass into runapplication
            - output_dir: directory for output files
        Returns:
            - actual_output, dictionary, maps table name to file name of run results
        """
        # TODO: This method doesn't require arg {tables}.  Eliminate.

        # TODO: This method is a vestige of the former architecture of this class.
        # Eliminate it.

        # Call runapplication on the configuration file.
        actual_output = self.run_application(config_file, output_dir)

        return actual_output


    def _list_outputs(self, outfileName_test, outfileName_expect):
        """
        Returns outputs from test outputs and expected outputs.

        Parameters:
            - outfileName_test: file name of output from test run of application
            - outfileName_expect: file name of the expected output
        Output:
            - test_list: the contents of the test output in a list
            - output_list: the contents of the expected output in a list
        Throws:
            - Assertion error if files do not exist.
        """

        # Get test results.
        self.assertTrue(
            os.path.isfile(outfileName_test),
            msg='Cannot find file {' +outfileName_test +'} of results from running application'
            )
        with open(outfileName_test, 'r') as ff:
            reader = csv.reader(ff)
            test_list = list(reader)

        # Get expected results.
        self.assertTrue(
            os.path.isfile(outfileName_expect),
            msg='Cannot find file {' +outfileName_expect +'} of expected results'
            )
        with open(outfileName_test, 'r') as ff:
            reader = csv.reader(ff)
            expected_list = list(reader)

        return test_list, expected_list


    def _diff_checker(self, test_list, expected_list):
        """
        Checks for differences between the new csv file and the expected csv
        file. If the values are strings, it's checked for exactness.  Numerical
        values are checked using the nearly_same function defined below.

        Parameters:
            - test_list: test file contents in a list
            - expected_list: expected file contents as a list
        Throws:
            - Assertion error if the numbers are not nearly same, or the file
                does not match
        """
        test_dict = {}
        expected_dict = {}

        for test_header in test_list[0]:
            test_dict[test_header] = []

        for expected_header in expected_list[0]:
            expected_dict[expected_header] = []

        i = 0
        for elem in test_list:
            for m in test_list[0]:
                test_dict[m].append(elem[i%len(test_list[0])])
                i += 1

        i = 0
        for elem in expected_list:
            for m in expected_list[0]:
                expected_dict[m].append(elem[i%len(expected_list[0])])
                i += 1

        # Check for differences.
        i = 1
        for key in test_dict:
            self.assertTrue((len(test_dict[key]) > 1),
                    "The application did not run correctly.")
            if (self._is_num(test_dict[key][1])):
                self.assertEqual(test_dict[key][0], expected_dict[key][0],\
                        "Headers don't match.")
                # Arrays to hold numerical values of this column.
                # (They're parsed as strings to begin with.)
                test_val_arr = []
                expe_val_arr = []
                for val in test_dict[key][1:]:
                    test_val_arr.append(float(val))
                    expe_val_arr.append(float(expected_dict[key][i]))
                    i += 1
                # Check for approximate sameness.
                self.nearly_same(test_val_arr, expe_val_arr, key)
            else:
                self.assertEqual(test_dict[key], expected_dict[key], \
                    "Something in the " + key + " header doesn't match. They \
                    are " + str(test_dict[key]) + ',' + \
                    str(expected_dict[key])+ '.')
            i = 1

    def _is_num(self, s):
        """
        Check to see if s a number.

        Parameters:
            - s: a number.
        Returns:
            - True or False indicating if given s is a number.
        """
        try:
            float(s)
            return True
        except ValueError:
            return False


    def nearly_same(self, xxs, yys, key='', absTol=1e-12, relTol=1e-6):
        """
        Compare two numbers or arrays, checking all elements are nearly equal.

        Parameters:
            - xxs, yys: two lists of numbers to compare
            - key: the key to the column we are comparing in output files
            - absTol: absolute tolerance
            - relTol: relative tolerance
        Returns: True if the two lists are nearly the same; else False.  TODO: Actually, assertion error in that case, but this may change.
        Throws: Assertion error if xxs and yys not nearly the same.
        """
        #
        # Coerce scalar to array if necessary.
        if( not hasattr(xxs, '__iter__') ):
            xxs = [xxs]
        if( not hasattr(yys, '__iter__') ):
            yys = [yys]
        lenXX = len(xxs)
        nearlySame = (len(yys) == lenXX)
        idx = 0
        while( nearlySame and idx<lenXX ):
            xx = xxs[idx]
            absDiff = math.fabs(yys[idx]-xx)
            if (absDiff>absTol and absDiff>relTol*math.fabs(xx)):
                self.assertFalse((absDiff>absTol and \
                        absDiff>relTol*math.fabs(xx)),
                    (key + ' is not nearly same: ' + str(xx) + ' ' \
                    + str(yys[idx]) + ' idx: ' + str(idx) + ' absDiff: ' \
                    + str(absDiff), ' relDiff: '+ str(absDiff/math.fabs(xx))))
                nearlySame = False
            idx += 1
        return( nearlySame )


    def run_it(self, ini_file, expected_output, clean_up=False):
        """
        Runs the application and checks the output with the expected output.
            Will clean up output files if clean_up is set to true.

        Parameters:
            - ini_file: configuration file to be passed into runapplication
            - expected_output: dictionary, maps table name to file name of expected results
            - clean_up: if it should clean newly made files or not
        Throws: Assertion error if the files do not match.
        """
        config = ConfigParser()
        # read the init file
        config.read(ini_file)
        # grab application name
        application = config['global_settings']['application']
        # Create temp dir for output
        stmp = tempfile.mkdtemp()
        # run application
        actual_output = self._call_runapplication(expected_output.keys(), \
                                               ini_file, stmp)
        for tableName in expected_output:
            # get outputs
            test_list, expected_list = \
                self._list_outputs(actual_output[tableName], expected_output[tableName])
            # check for similarity
            self._diff_checker(test_list, expected_list)

        if clean_up:
            for tableName in actual_output:
                os.remove(actual_output[tableName])
            logFiles = [
                fileName for fileName in os.listdir()  \
                    if (application in fileName and '.log' in fileName)
                ]
            if( len(logFiles) > 0 ):
                newestLog = max(logFiles, key=os.path.getctime)
                os.remove(newestLog)
