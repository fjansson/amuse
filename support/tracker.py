import subprocess
import socket, os

import time
import urlparse
import threading
import json
import os.path
import os
import sys

import webbrowser

from xml.dom import minidom

from optparse import OptionParser

import webserver
import background_test
import project
import pickle

import Queue

background_test.RunTests.instance = background_test.RunTests()

class late(object):
    def __init__(self, initializer):
        
        self.initializer = initializer
        self.__doc__ = self.initializer.__doc__
        
    def __get__(self, instance, owner):
        if instance is None:
            return self
        value = self.initializer(instance)
        setattr(instance,self.initializer.__name__, value)
        return value
        
class SendAnEmail(object):
    
    def __init__(self, **keyword_arguments):
        if len(keyword_arguments) > 0:
            for key, value in keyword_arguments.iteritems():
                setattr(self, key, value)
                self.start()

    def start(self):
        
        call = ['mail','-s',self.subject, '-r', self.sender_email_address]
        call.extend(self.recipients)
        
        print call
        
        process = subprocess.Popen(
            call,
            stdout=subprocess.PIPE,
            stdin =subprocess.PIPE,
            stderr=subprocess.PIPE
        )
            
        stdout, stderr = process.communicate(self.mail_contents)
        
        if process.returncode != 0:
            raise Exception("Could not send e-mail, error output was {0}".format(stderr))
        
    @late
    def sender_email_address(self):
        if "EMAIL" in os.environ:
            return os.environ["EMAIL"]
        else:
            return 'noreply@{0}'.format(socket.getfqdn())
    
    @late
    def mail_contents(self):
        return 'Mail send by the SendAnEmail class\nContents not provided\n'
    
    @late
    def subject(self):
        return 'Automatic mail subject'
        


def get_first_element_with_tag(parent, name):
    for node in parent.childNodes:
        if node.nodeType == minidom.Node.ELEMENT_NODE and \
            (name == "*" or node.tagName == name):
            return node
    return None


header = """\
Dear {name},

"""

errored_start = """\
This is to inform you that your commit had errors.
"""
success_start = """\
This is to inform you that your commit had no errors, well done!
"""

commit_info = """\
AUTHOR   : {author}
REVISION : {revision}
DATE     : {date}
MESSAGE  : {msg}
"""

error_info = """\
NUMBER OF ERRORS    : {number_of_errors:>5d}
"""

tests_info = """\
NUMBER OF TESTS     : {number_of_tests:>5d}
TIME TAKEN(seconds) : {number_of_seconds:>6.1f}
"""
footer = """\
Regards,

The AMUSE automated testing system
"""

errored_email_subject = """Found {number_of_errors} error(s) in revision {revision}"""
success_email_subject = """For revision revision {revision}, all {number_of_tests} tests were successful!"""


class RunAllTestsOnASvnCommit(object):
    DEFAULT = None
    
    def __init__(self):
        self.queue =  Queue.Queue()
        self.must_run = False

    @classmethod
    def default(cls):
        if cls.DEFAULT is None:
            cls.DEFAULT = cls()
        return cls.DEFAULT
    
    @late
    def working_directory(self):
        path = os.path.dirname(os.path.dirname(__file__))
        path = os.path.abspath(os.path.join(path, 'working-copy'))
        return path
    
    @late
    def directories(self):
        return [os.path.join(self.working_directory, x) for x in project.DIRECTORIES]
    
    @late
    def mapping_from_author_to_email(self):
        path = os.path.dirname(__file__)
        path = os.path.join(path, "authors.map")
        with open(path, 'r') as f:
            return pickle.load(f)
        
    def update_from_svn(self, revision):
        subprocess.call(['svn','update', '-r', revision], cwd = self.working_directory)
        
    def build_code(self):
        subprocess.call(['make','clean'], cwd = self.working_directory)
        subprocess.call(['make'], cwd = self.working_directory)
        
    def get_author_date_and_msg_for(self, revision):
        process = subprocess.Popen(['svn','log', '-r', revision, '--xml'], cwd = self.working_directory, stdout = subprocess.PIPE)
        result, ignore = process.communicate()
        
        if not process.returncode == 0:
            raise Exception("could not retrieve log for revision {0}" + revision)
            
        doc = minidom.parseString(result)
        results = []
        entry = list(doc.getElementsByTagName('logentry'))[0]
        author  =  get_first_element_with_tag(entry, "author").firstChild.data
        date_string = get_first_element_with_tag(entry, "date").firstChild.data
        msg_string = get_first_element_with_tag(entry, "msg").firstChild.data
            
        return author, date_string, msg_string
        
    def run_all_tests(self):
        background_test.RunTests.DIRECTORIES = self.directories
        background_test.RunTests.WORKING_DIRECTORY = self.working_directory
        return background_test.RunTests.instance.run_tests(None)
        
    def send_report_as_email_to(self, report, recipient):
        uc = SendAnEmail()
               
        contents = []
        contents.append(header.format(**report))
        
        if report["number_of_errors"] > 0:
            contents.append(errored_start.format(**report))
        else:
            contents.append(success_start.format(**report))
            
        contents.append(commit_info.format(**report))
        
        if report["number_of_errors"] > 0:
            contents.append(error_info.format(**report))
            
        contents.append(tests_info.format(**report))
        contents.append(footer.format(**report))
        
        uc.mail_contents = '\n'.join(contents)
        
        if report["number_of_errors"] > 0:
            uc.subject = errored_email_subject.format(**report)
        else:
            uc.subject = success_email_subject.format(**report)
        
        if not recipient is None:
            uc.recipients = [recipient]
            uc.start()
        
        uc.recipients = [self.admin_email_address]
        uc.start()
        
        
    def check_svn_commit(self,revision):
        
        
        self.update_from_svn(revision)
        self.build_code()
        
        test_report = self.run_all_tests()
        
        author, date, msg = self.get_author_date_and_msg_for(revision)
        if author in self.mapping_from_author_to_email:
            name, email = self.mapping_from_author_to_email[author]
        else:
            name, email = 'Admin', None
        
        report = {}
        report['author'] = author
        report['date'] = date
        report['msg'] = msg
        report['name'] = name
        report['number_of_errors'] = test_report.errors + test_report.failures
        report['number_of_tests'] = test_report.tests
        report['number_of_seconds'] = test_report.end_time - test_report.start_time
        report['revision']  = revision
        
        self.mapping_from_revision_to_report[int(revision)] = report
        self.dump_revision_reports()
        
        
        self.send_report_as_email_to(report, email)
        
        
    @late
    def admin_email_address(self):
        if "EMAIL" in os.environ:
            return os.environ["EMAIL"]
        else:
            return None
            
    def start(self):
        self.thread = threading.Thread(target = self.runloop)
        self.thread.daemon = True
        self.must_run = True
        self.thread.start()
    
          
    def runloop(self): 
        while self.must_run:
            revision = self.queue.get()
            if revision is None:
                self.must_run = False
            else:
                self.check_svn_commit(revision)
        
        
    def queue_check(self, revision):
        self.queue.put(revision)
        
    def stop(self):
        self.queue.put(None)
        
    def number_of_tested_revisions(self):
        return len(self.mapping_from_revision_to_report)
        
    def dump_revision_reports(self):
        path = os.path.dirname(__file__)
        path = os.path.join(path, "reports.map")
        with open(path, 'w') as f:
          pickle.dump(self.mapping_from_revision_to_report, f)
    
    @late
    def mapping_from_revision_to_report(self):
        path = os.path.dirname(__file__)
        path = os.path.join(path, "reports.map")
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return pickle.load(f)
            except IOError:
                return {}
        else:
            return {}
        
        
class HandleRequest(webserver.HandleRequest):
   
    def do_check_svn_commit(self):
        parameters = urlparse.parse_qs(self.parsed_path.query)
        revision = parameters['rev'][0]
        
        
        self.server.tracker.queue_check(revision)
        
        string = json.dumps("test for revision {0} queued".format(revision))
        content_type = 'text/javascript'
        return string, content_type
        
    
    def do_ping(self):
        string = json.dumps(True)
        content_type = 'text/javascript'
        return string, content_type
        
    def index_file(self):
        if True:
            return ("nothing here", "text/html")
            
        base = os.path.split(__file__)[0]
        filename = os.path.join(base, "tracker.html")
        with open(filename, "r") as file:
            contents = file.read()
        return contents, 'text/html'
            

class ContinuosTestWebServer(webserver.WebServer):
    
    def __init__(self, port):
        webserver.WebServer.__init__(self,  port, HandleRequest)
        self.tracker = RunAllTestsOnASvnCommit()
        
        
    def stop(self):
        self.tracker.stop()
        self.shutdown()
        
            
if __name__ == '__main__':
    parser = OptionParser() 
    
    parser.add_option("-p", "--port", 
      dest="serverport",
      help="start serving on PORT", 
      metavar="PORT", 
      default=9075,
      type="int")
    
    parser.add_option("-a", "--admin", 
      dest="admin_email",
      help="e-mail address of the admin", 
      default=None,
      type="string")
      
    (options, args) = parser.parse_args()
    
    print "starting server on port: ", options.serverport
      
    server = ContinuosTestWebServer(options.serverport)
    if options.admin_email:
        server.tracker.admin_email_address = options.admin_email
    server.tracker.start()
    server.start()

    

        

        


    
