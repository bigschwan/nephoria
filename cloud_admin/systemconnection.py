
import copy
import logging
from prettytable import PrettyTable
import re
from cloud_admin.access.autocreds import AutoCreds
from cloud_admin.services.serviceconnection import ServiceConnection
from cloud_admin.hosts.eucahost import EucaHost
from cloud_utils.system_utils.machine import Machine
from cloud_utils.log_utils.eulogger import Eulogger
from cloud_utils.log_utils import markup


class SystemConnection(ServiceConnection):

    def __init__(self,
                 hostname,
                 username='root',
                 password=None,
                 keypath=None,
                 proxy_hostname=None,
                 proxy_username='root',
                 proxy_password=None,
                 proxy_keypath=None,
                 config_yml=None,
                 config_qa=None,
                 credpath=None,
                 aws_access_key=None,
                 aws_secret_key=None,
                 log_level='INFO',
                 boto_debug_level=0,
                 euca_user='admin',
                 euca_account='eucalyptus',
                 ):
        self.clc_connect_kwargs = {
            'hostname': hostname,
            'username': username,
            'password': password,
            'keypath': keypath,
            'proxy_hostname': proxy_hostname,
            'proxy_username': proxy_username,
            'proxy_password': proxy_password,
            'proxy_keypath': proxy_keypath
        }
        self._clc_machine = None
        self.hostname = hostname
        self.config_qa = config_qa
        self.config_yml = config_yml
        # self._aws_access_key = aws_access_key
        # self._aws_secret_key = aws_secret_key
        self._eucahosts = {}
        self._credpath = credpath
        self.log = Eulogger(identifier=self.__class__.__name__, stdout_level=log_level)
        self.creds = AutoCreds(credpath=self._credpath,
                               aws_access_key=aws_access_key,
                               aws_secret_key=aws_secret_key,
                               aws_account_name=euca_account,
                               aws_user_name=euca_user,
                               logger=self.log,
                               **self.clc_connect_kwargs)
        super(SystemConnection, self).__init__(hostname=hostname,
                                                aws_secret_key=self.creds.aws_secret_key,
                                                aws_access_key=self.creds.aws_access_key,
                                                logger=self.log,
                                                boto_debug_level=boto_debug_level)

    def set_loglevel(self, level, parent=False):
        """
        wrapper for log.setLevel, accept int or string.
        Levels can be found in logging class. At the time this was written they are:
        CRITICAL:50
        DEBUG:10
        ERROR:40
        FATAL:50
        INFO:20
        NOTSET:0
        WARN:30
        WARNING:30
        """
        level = level or logging.NOTSET
        if not isinstance(level, int) and not isinstance(level, basestring):
            raise ValueError('set_loglevel. Level must be of type int or string, got: "{0}/{1}"'
                             .format(level, type(level)))
        if isinstance(level, basestring):
            level = getattr(logging, str(level).upper())
        return self.log.set_parentloglevel(level)

    @property
    def clc_machine(self):
        if not self._clc_machine:
            if self.clc_connect_kwargs['hostname']:
                if self.eucahosts[self.clc_connect_kwargs['hostname']]:
                    self._clc_machine = self.eucahosts[self.clc_connect_kwargs['hostname']]
                else:
                    self._clc_machine = Machine(**self.clc_connect_kwargs)
                    self.eucahosts[self.clc_connect_kwargs['hostname']] = self._clc_machine
        return self._clc_machine

    @property
    def eucahosts(self):
        if not self._eucahosts:
            self._eucahosts = self._update_host_list()
        return self._eucahosts

    def _update_host_list(self):
        machines = self.get_all_machine_mappings()
        connect_kwargs = copy.copy(self.clc_connect_kwargs)
        if 'hostname' in connect_kwargs:
            connect_kwargs.pop('hostname')
        for ip, services in machines.iteritems():
            self._eucahosts[ip] = EucaHost(hostname=ip, services=services, **connect_kwargs)
        return self._eucahosts

    def get_hosts_by_service_type(self, servicetype):
        ret_list = []
        for ip, host in self.eucahosts.iteritems():
            for service in host.services:
                if service.type == servicetype:
                    ret_list.append(host)
        return ret_list

    def get_hosts_for_cloud_controllers(self):
        clc = None
        return self.get_hosts_by_service_type(servicetype='eucalyptus')

    def get_hosts_for_node_controllers(self, partition=None, instanceid=None):
        ncs = self.get_hosts_by_service_type(servicetype='node')
        if not partition and not instanceid:
            return ncs
        retlist = []
        for nc in ncs:
            if instanceid:
                for instance in nc.instances:
                    if instance == instanceid:
                        return [nc]
            if nc.partition == partition:
                retlist.append(nc)
        return retlist

    def get_hosts_cluster_controllers(self, partition=None):
        ccs = self.get_hosts_by_service_type(servicetype='cluster')
        if not partition:
            return ccs
        retlist = []
        for cc in ccs:
            if cc.partition == partition:
                retlist.append(cc)
        return retlist

    def get_hosts_for_storage_controllers(self, partition=None):
        scs = self.get_hosts_by_service_type(servicetype='storage')
        if not partition:
            return scs
        retlist = []
        for sc in scs:
            if sc.partition == partition:
                retlist.append(sc)
        return retlist

    def get_hosts_for_ufs(self):
        ufs = None
        out = self.get_hosts_by_service_type(servicetype='user-api')
        if out:
            ufs = out[0]
        return ufs

    def get_hosts_for_walrus(self):
        walrus = None
        out = self.get_hosts_by_service_type(servicetype='walrusbackend')
        if out:
            walrus = out[0]
        return walrus

    def show_cloud_legacy_summary(self,  print_method=None, print_table=True):
        ret = ""
        print_method = print_method or self.log.info
        pt = PrettyTable(['# HOST', 'DISTRO', 'VER', 'ARCH', 'ZONE', 'SERVICE CODES'])
        pt.align = 'l'
        pt.border = 0
        for ip, host in self.eucahosts.iteritems():
            split = host.summary_string.split()
            service_codes = " ".join(split[5:])
            pt.add_row([split[0], split[1], split[2], split[3], split[4], service_codes])
            ret += "{0}\n".format(host.summary_string)
        if print_table:
            print_method("\n{0}\n".format(str(pt)))
        else:
            return pt


    def show_hosts(self, host_dict=None, partition=None, service_type=None,
                              columns=4, print_method=None, print_table=True):
        print_method = print_method or self._show_method
        ins_id_len = 10
        ins_type_len = 13
        ins_dev_len = 16
        ins_st_len = 15
        ins_total = (ins_id_len + ins_dev_len + ins_type_len + ins_st_len) + 5
        machine_hdr = (markup('MACHINE'), 20)
        service_hdr = (markup('SERVICES'), 100)
        pt = PrettyTable([machine_hdr[0], service_hdr[0]])
        pt.align = 'l'
        pt.hrules = 1
        pt.max_width[machine_hdr[0]] = machine_hdr[1]
        total = []
        eucahosts = host_dict or self.eucahosts
        if not isinstance(eucahosts, dict):
            raise ValueError('show_machine_mappings requires dict example: '
                             '{"host ip":[host objs]}, got:"{0}/{1}"'
                             .format(eucahosts, type(eucahosts)))
        # To format the tables services, print them all at once and then sort the table
        # rows string into the machines columns
        for hostip, host in eucahosts.iteritems():
            for serv in host.services:
                total.append(serv)
                if serv.child_services:
                    total.extend(serv.child_services)
        # Create a large table showing the service states, grab the first 3 columns
        # for type, name, state, and zone
        servpt = self.show_services(total, print_table=False)
        serv_lines = servpt.get_string(border=0, padding_width=2,
                                       fields=servpt._field_names[0: columns]).splitlines()
        header = serv_lines[0]
        ansi_escape = re.compile(r'\x1b[^m]*m')
        # Now build the machine table...
        for hostip, host in eucahosts.iteritems():
            assert isinstance(host, EucaHost)
            servbuf = header + "\n"
            mservices = []
            # Get the child services (ie for UFS)
            for serv in host.services:
                mservices.append(serv)
                mservices.extend(serv.child_services)
            for serv in mservices:
                for line in serv_lines:
                    # Remove the ansi markup for parsing purposes, but leave it in the
                    # displayed line
                    clean_line = ansi_escape.sub('', line)
                    splitline = clean_line.split()
                    if len(splitline) < 2:
                        continue
                    line_type = splitline[0]
                    line_name = splitline[1]
                    # Pull matching lines out of the pre-formatted service table...
                    if (splitline and re.match("^{0}$".format(serv.type), line_type) and
                            re.match("^{0}$".format(serv.name), line_name)):
                        # Add this line to the services to be displayed for this machine
                        if line_name not in servbuf:
                            servbuf += line + "\n"
                if serv.type == 'node' and getattr(serv, 'instances', None):
                    servbuf += "\n" + markup('INSTANCES', [1, 4]) + " \n"
                    for x in serv.instances:
                        servbuf += ("{0}{1}{2}{3}"
                                    .format(str(x.id).ljust(ins_id_len),
                                            str('(' + x.state + '),').ljust(ins_st_len),
                                            str(x.instance_type + ",").ljust(ins_type_len),
                                            str(x.root_device_type).ljust(ins_dev_len))
                                    .ljust(ins_total)).strip() + "\n"
            host_info = "{0}\n".format(markup(hostip, [1, 4, 94])).ljust(machine_hdr[1])
            sys_pt = PrettyTable(['name', 'value', 'percent'])
            sys_pt.header = False
            sys_pt.border = 0
            sys_pt.align = 'l'
            sys_pt.padding_width = 0
            sys_pt.add_row([markup("Mem:"), "", ""])
            free = host.get_free_mem() or 0
            used = host.get_used_mem() or 0
            total = host.get_total_mem() or 0
            swap = host.get_swap_used() or 0
            per_used = "{0:.2f}".format(used / float(total))
            per_free = "{0:.2f}".format(free / float(total))
            per_swap = "{0:.2f}".format(swap / float(total))
            sys_pt.add_row([" Used:", "{0}".format(used), "{0}%".format(per_used)])
            sys_pt.add_row([" Free:", "{0}".format(free), "{0}%".format(per_free)])
            sys_pt.add_row([" Swap:", "{0}".format(swap), "{0}%".format(per_swap)])
            sys_pt.add_row([markup("CPU:"), "", ""])
            cpu_info = host.cpu_info
            all = cpu_info.pop('all', None)
            for cpu in sorted(cpu_info):
                values = cpu_info[cpu]
                sys_pt.add_row([" #{0}:".format(cpu), "{0}%".format(values.get('used',None)), ""])
            # if all:
            #     sys_pt.add_row([' ALL:', "{0}%".format(values.get('used',None)), ""])


            host_info += "\n{0}\n".format(sys_pt)
            pt.add_row(["{0}\n{1}".format(str("").rjust(machine_hdr[1]), host_info), servbuf])
        if print_table:
            print_method("\n{0}\n".format(pt.get_string(sortby=pt.field_names[1])))
        else:
            return pt


    def build_machine_dict_from_config(cls):
        raise NotImplementedError()

    def build_machine_dict_from_cloud_services(self):
        raise NotImplementedError('not yet implemented')
