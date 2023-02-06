import yaml
import time
import os
import queue
import re
from pathlib import Path
from pprint import pformat
from threading import Thread
from sys import argv
from datetime import datetime
from netmiko import ConnectHandler


#######################################################################################
# ------------------------------ classes part ----------------------------------------#
#######################################################################################

class CellSiteGateway:

    def __init__(self, ip, host):
        self.hostname = host
        self.ip_address = ip
        self.os_type = "cisco_ios"

        self.connection_status = True  # failed connection status, False if connection fails
        self.connection_error_msg = ""  # connection error message

        self.ios_list = []
        self.ios_list_short = []
        self.logging = []
        self.sfp_vendor_cisco = []  # True False
        self.sfp_vendor = []
        self.error = False
        self.error_msg = []
        self.pagg_xe = None
        self.current_ios = None
        self.current_ios_short = None
        self.md5_correct = None
        self.md5 = None
        self.ios_copied = ""
        self.ios_copied_short = None
        self.boot = ""
        self.boot_short = None
        self.ios_to_delete = []
        self.ios_to_delete_short = []
        self.delete_files = []
        self.squeeze_result = None
        self.current_boot = ""
        self.current_boot_short = None


#######################################################################################
# ---------------------------------- common part -------------------------------------#
#######################################################################################

def get_argv(arguments):
    settings = {"maxth": 20,
                "cfg": False,
                "force": False}
    for arg in arguments:
        if arg == "cfg":
            settings["cfg"] = True
        elif arg == "force":
            settings["force"] = True
            settings["cfg"] = True
    print()
    print(f"max threads:...................{settings['maxth']}\n"
          f"CFG mdoe:......................{settings['cfg']}\n"
          f"Force mdoe:....................{settings['force']}")

    return settings


def get_user_pw():
    with open("psw.yaml") as file:
        user_psw = yaml.load(file, yaml.SafeLoader)

    return user_psw[0], user_psw[1]


def get_devinfo():
    devs = []
    with open("devices.yaml", "r") as file:
        devices_info = yaml.load(file, yaml.SafeLoader)
        for hostname, ip_address in devices_info.items():
            dev = CellSiteGateway(ip=ip_address, host=hostname)
            devs.append(dev)
    print()
    return devs


def write_logs(devs, log_folder, settings):    
    failed_connection = 0
    errors = 0
    timenow = datetime.now()
    current_date = timenow.strftime("%Y.%m.%d")
    current_time = timenow.strftime("%H.%M.%S")
    folder = f"logs/{current_date}"
    if not os.path.exists(folder):
        os.mkdir(folder)

    err_msg = log_folder / f"{current_time}_connection_error_msg.txt"
    log = log_folder / f"{current_time}_logs.txt"
    error = log_folder / f"{current_time}_error_logs.txt"
    vendor = log_folder / f"{current_time}_sfp_vendor.txt"

    err_msg_file = open(err_msg, "w")
    err_msg_file.write(f"{current_date} {current_time}\n\n")

    log_file = open(log, "w")
    log_file.write(f"{current_date} {current_time}\n\n")

    error_file = open(error, "w")
    error_file.write(f"{current_date} {current_time}\n\n")

    vendor_file = open(vendor, "w")
    vendor_file.write(f"{current_date} {current_time}\n\n")

    for dev in devs:
        if not dev.connection_status:
            failed_connection += 1
            err_msg_file.write("-" * 80 + "\n")
            err_msg_file.write(f"{dev.hostname} : {dev.ip_address}\n\n")
            err_msg_file.write(f"{dev.connection_error_msg}\n")
        else:
            log_file.write("-" * 80 + "\n")
            log_file.write(f"{dev.hostname} : {dev.ip_address}\n\n")
            log_file.write("".join(dev.logging))
            log_file.write("\n\n")
            vendor_file.write(f"{dev.hostname}: {dev.sfp_vendor}\n")
        if dev.error:
            errors += 1
            error_file.write("-" * 80 + "\n")
            error_file.write(f"{dev.hostname} : {dev.ip_address}\n\n")
            error_file.write(pformat(dev.error_msg))
            error_file.write("\n\n")

    err_msg_file.close()
    log_file.close()
    error_file.close()
    vendor_file.close()

    if not settings["cfg"]:
        log.unlink() 

    if all([dev.connection_status is True for dev in devs]):
        err_msg.unlink()

    if all([dev.error is False for dev in devs]):
        error.unlink()

    return failed_connection, errors


#######################################################################################
# ------------------------------ def         -----------------------------------------#
#######################################################################################

def dir_ios(dev, connection):
    dirflash = connection.send_command(r"dir flash:", read_timeout=20)
    compile = re.compile(r"\d+ +\S+ +\d+ +.* (\S+)")
    for line in dirflash.splitlines():
        match = re.search(compile, line)
        if match:
            if ".bin" in match[1]:
                dev.ios_list.append(match[1])
            elif ".lic" not in match[1]:
                dev.delete_files.append(match[1])
    

def controller(dev, connection):
    show_uplink = connection.send_command(r"sh int descr | in UPLINK|pagg|csg", read_timeout=20)
    uplink = ["pagg", "UPLINK", "csg"]
    ports = []

    for line in show_uplink.splitlines():
        if any([i in line for i in uplink]):
            p = line.split()[0]
            if "Vl" not in p and "Po" not in p:
                ports.append(p)

    for port in ports:
        show_controller = connection.send_command(f"sh controllers {port} | in vendor_name", read_timeout=20)
        for i in show_controller.splitlines():
            if "vendor_name" in i:
                if "CISCO" in i:
                    dev.sfp_vendor_cisco.append(True)
                    dev.sfp_vendor.append(i.split()[-1])
                else:
                    dev.sfp_vendor_cisco.append(False)
                    dev.sfp_vendor.append(i.split()[-1])
                    dev.error = True
                    dev.error_msg.append(f"vendor name is not cisco: {i.split()[-1]}")           

    if len(ports) != len(dev.sfp_vendor):
        dev.error = True
        dev.error_msg.append(f"vendor name is not found: {ports} {dev.sfp_vendor}")


def define_pagg_xe(dev, connection):
    pagg = connection.send_command(r"sh isis hostname | in pagg", read_timeout=20)
    
    xe = ("alma-003001-pagg-1",
          "alma-004001-pagg-1",
          "alma-006001-pagg-1",
          "alma-062001-pagg-1",
          "alma-020001-pagg-1",
          "alma-023001-pagg-1",
          "alma-051001-pagg-1",
          "alma-040001-pagg-1",
          "alma-048001-pagg-1",
          "alma-052001-pagg-1",
          "alma-073001-pagg-1",
          "alma-521001-pagg-1",
          "asta-032001-pagg-1",
          "asta-032001-pagg-2",
          "asta-036001-pagg-1",
          "asta-036001-pagg-2",
          "asta-038001-pagg-1",
          "asta-240001-pagg-1",
          "asta-240001-pagg-2")
          
    for i in pagg.splitlines():
        if "pagg" in i:
            p = i.split()[-1]
            if p in xe:
                dev.pagg_xe = True
            else:
                dev.pagg_xe = False
            

def current_ios(dev, connection):
    current_ios_log = connection.send_command(f"sh ver | in Cisco IOS Software", read_timeout=20)
    compile = re.compile(r"Version (\S+),")

    for a in current_ios_log.splitlines():
        match = re.search(compile, a)
        if match:
            current_ios_version = match[1]
            i1 = current_ios_version.replace(".", "")
            i2 = i1.replace("(", "-")
            i3 = i2.replace(")", ".")
            dev.current_ios = f"asr901-universalk9-mz.{i3}.bin"


def current_boot(dev, connection):
    boot = connection.send_command(f"sh run | in boot system flash", read_timeout=20)
    for i in boot.splitlines():
        if "bin" in i:
            dev.current_boot = i.split()[-1]


def parse_lst(dev):
    if dev.pagg_xe:
        if dev.current_boot != "asr901-universalk9-mz.155-3.S10.bin":
            dev.boot = "asr901-universalk9-mz.155-3.S10.bin"
        if dev.current_ios == "asr901-universalk9-mz.155-3.S10.bin":
            correct_ios = ("asr901-universalk9-mz.155-3.S10.bin")
        else:
            correct_ios = ("asr901-universalk9-mz.155-3.S10.bin", dev.current_ios)
            if "asr901-universalk9-mz.155-3.S10.bin" not in dev.ios_list:
                dev.ios_copied = "asr901-universalk9-mz.155-3.S10.bin"
    else:
        if dev.current_boot != "asr901-universalk9-mz.156-2.SP9.bin":
            dev.boot = "asr901-universalk9-mz.156-2.SP9.bin"
        if dev.current_ios == "asr901-universalk9-mz.156-2.SP9.bin":
            correct_ios = ("asr901-universalk9-mz.156-2.SP9.bin", "asr901-universalk9-mz.155-3.S10.bin")
            if "asr901-universalk9-mz.155-3.S10.bin" not in dev.ios_list:
                dev.ios_copied = "asr901-universalk9-mz.155-3.S10.bin"
        elif dev.current_ios == "asr901-universalk9-mz.155-3.S10.bin":
            correct_ios = ("asr901-universalk9-mz.156-2.SP9.bin", "asr901-universalk9-mz.155-3.S10.bin")
            if "asr901-universalk9-mz.156-2.SP9.bin" not in dev.ios_list:
                dev.ios_copied = "asr901-universalk9-mz.156-2.SP9.bin"
        else:
            correct_ios = ("asr901-universalk9-mz.156-2.SP9.bin", dev.current_ios)
            if "asr901-universalk9-mz.156-2.SP9.bin" not in dev.ios_list:
                dev.ios_copied = "asr901-universalk9-mz.156-2.SP9.bin"

    for i in dev.ios_list:
        if i not in correct_ios:
            dev.ios_to_delete.append(i)

    if dev.ios_copied == "asr901-universalk9-mz.155-3.S10.bin":
        dev.md5 = "87d293427559873cb5e7f36ec1599733"
    elif dev.ios_copied == "asr901-universalk9-mz.156-2.SP9.bin":
        dev.md5 = "d2864fe9a1725cde1d12d7e237b6be2f"


def short_ios(dev):
    compile = re.compile(r"mz.(\S+).bin")

    match_ios = re.search(compile, dev.current_ios)
    if match_ios:
        dev.current_ios_short = match_ios[1]

    match_copied = re.search(compile, dev.ios_copied)
    if match_copied:
        dev.ios_copied_short = match_copied[1]

    match_boot = re.search(compile, dev.boot)
    if match_boot:
        dev.boot_short = match_boot[1]

    match_curr_boot = re.search(compile, dev.current_boot)
    if match_curr_boot:
        dev.current_boot_short = match_curr_boot[1]

    for i in dev.ios_to_delete:
        match = re.search(compile, i)
        if match:
            dev.ios_to_delete_short.append(match[1])      

    for j in dev.ios_list:
        match_list = re.search(compile, j)
        if match_list:
            dev.ios_list_short.append(match_list[1])   


def delete_ios(dev, connection):
    if dev.ios_to_delete:
        for i in dev.ios_to_delete:
            dev.logging.append(connection.send_command(f"delete flash:{i}", 
                                                        expect_string=r"Delete filename",
                                                        strip_command=False, strip_prompt=False, 
                                                        read_timeout=20))
            dev.logging.append(connection.send_command("", 
                                                        expect_string=r"confirm",
                                                        strip_command=False, strip_prompt=False, 
                                                        read_timeout=20))
            dev.logging.append(connection.send_command("", 
                                                        expect_string=r"#",
                                                        strip_command=False, strip_prompt=False, 
                                                        read_timeout=20))
    if dev.delete_files:
        for j in dev.delete_files:
            dev.logging.append(connection.send_command(f"delete flash:{j}", 
                                                        expect_string=r"Delete filename",
                                                        strip_command=False, strip_prompt=False, 
                                                        read_timeout=20))
            dev.logging.append(connection.send_command("", 
                                                        expect_string=r"confirm",
                                                        strip_command=False, strip_prompt=False, 
                                                        read_timeout=20))
            dev.logging.append(connection.send_command("", 
                                                        expect_string=r"#",
                                                        strip_command=False, strip_prompt=False, 
                                                        read_timeout=20))


def squeeze(dev, connection):
    if dev.ios_to_delete or dev.delete_files:
        dev.logging.append(connection.send_command("squeeze flash:", expect_string=r"confirm",
                                                    strip_command=False, strip_prompt=False, 
                                                    read_timeout=20))
        squeeze_log = connection.send_command("", expect_string=r"#", 
                                                read_timeout=1500,
                                                strip_command=False, strip_prompt=False)
        dev.logging.append(squeeze_log)

        if "Squeeze of flash complete" in squeeze_log:
            dev.squeeze_result = True
        else:
            print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] squeeze error")
            dev.error = True
            dev.error_msg.append("squeeze error")
            dev.squeeze_result = False


def copy(dev, connection, settings):
    if all(dev.sfp_vendor_cisco) or settings["force"]:
        dirflash_free = connection.send_command(r"dir flash: | in free", read_timeout=20)
        free_space = 0
        for line in dirflash_free.splitlines():
            if line.endswith(r"bytes free)"):
                free_space = int(line.split()[-3][1:])

        if dev.ios_copied:
            if free_space > 46000000:
                dev.logging.append(connection.send_command(f"copy ftp://212.19.149.62/{dev.ios_copied} flash:",
                                                            expect_string=r"Destination filename",
                                                            strip_command=False, strip_prompt=False,
                                                            read_timeout=20))
                dev.logging.append(connection.send_command("", expect_string=r"#",
                                                            strip_command=False, strip_prompt=False,
                                                            read_timeout=1500))

                
            else:
                print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] no free space: {free_space}")
                dev.error = True
                dev.error_msg.append(f"no free space: {free_space}")        

    else:
        print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] uplink sfp transceiver vendor is not cisco")
        dev.error = True
        dev.error_msg.append(f"uplink sfp transceiver vendor is not cisco: {dev.sfp_vendor}")


def check_md5(dev, connection):
    if dev.ios_copied:
        md5_log = connection.send_command(f"verify /md5 {dev.ios_copied}",
                                        strip_command=False, strip_prompt=False,
                                        read_timeout=1500)                           
        dev.logging.append(md5_log)
        if dev.md5 in md5_log:
            dev.md5_correct = True
        else:
            dev.error = True
            dev.error_msg.append("md5 checksum failed")
            dev.md5_correct = False


def set_boot(dev, connection):
    if dev.md5_correct and dev.boot:
        new_boot = ["no boot system", f"boot system flash {dev.boot}"]
        dev.logging.append(connection.send_config_set(new_boot,strip_command=False, strip_prompt=False,
                                                      read_timeout=20))
        try:
	        dev.logging.append(connection.save_config())
        except Exception as err_msg:
            dev.logging.append(f"COMMIT is OK after msg:{err_msg}")
            dev.logging.append(connection.send_command("\n", expect_string=r"#"))


def del_squeeze_copy(dev, connection, settings):
    dir_ios(dev, connection)
    controller(dev, connection)
    define_pagg_xe(dev, connection)
    current_ios(dev, connection)
    current_boot(dev, connection)
    parse_lst(dev)
    short_ios(dev)

    if settings["cfg"]:
        delete_ios(dev, connection)
        squeeze(dev, connection)
        copy(dev, connection, settings)
        check_md5(dev, connection)
        set_boot(dev, connection)
        
        print(f"{dev.hostname:25}{dev.ip_address:17}current ios:...................{dev.current_ios_short}\n"
                                           f"{'':42}ios in flash:..................{dev.ios_list_short}\n"
                                           f"{'':42}ios to delete:.................{dev.ios_to_delete_short}\n"
                                           f"{'':42}ios copied:....................{dev.ios_copied_short}\n"
                                           f"{'':42}boot current/new:..............{dev.current_boot_short}/{'didnt change' if dev.boot == '' else dev.boot_short}\n"
                                           f"{'':42}md5 correct:...................{dev.md5_correct}\n"
                                           f"{'':42}squeeze result:................{dev.squeeze_result}\n"
                                           f"{'':42}all sfp cisco:.................{all(dev.sfp_vendor_cisco)}/{dev.sfp_vendor}\n"
                                           f"{'':42}delete files:..................{dev.delete_files}") 

    else:
        print(f"{dev.hostname:25}{dev.ip_address:17}current ios:...................{dev.current_ios_short}\n"
                                           f"{'':42}ios in flash:..................{dev.ios_list_short}\n"
                                           f"{'':42}ios to delete:.................{dev.ios_to_delete_short}\n"
                                           f"{'':42}ios copied:....................{dev.ios_copied_short}\n"
                                           f"{'':42}boot current/new:..............{dev.current_boot_short}/{'didnt change' if dev.boot == '' else dev.boot_short}\n"
                                           f"{'':42}md5 correct:...................{dev.md5_correct}\n"
                                           f"{'':42}squeeze result:................{dev.squeeze_result}\n"
                                           f"{'':42}all sfp cisco:.................{all(dev.sfp_vendor_cisco)}/{dev.sfp_vendor}\n"
                                           f"{'':42}delete files:..................{dev.delete_files}")       


#######################################################################################
# ------------------------------ multithreading part ---------------------------------#
#######################################################################################

def connect_dev(my_username, my_password, dev_queue, settings):
    while True:
        dev = dev_queue.get()
        
        attempts = 1
        while True:
            try:
                ssh_conn = ConnectHandler(device_type=dev.os_type, ip=dev.ip_address,
                                          username=my_username, password=my_password)
                del_squeeze_copy(dev, ssh_conn, settings)
                ssh_conn.disconnect()
                dev_queue.task_done()
                break
            except Exception as err_msg:
                if attempts == 0:
                    dev.connection_status = False
                    dev.connection_error_msg = str(err_msg)
                    print(f"{dev.hostname:25}{dev.ip_address:17}connection failed after all attempts, {err_msg}")
                    try:
                        ssh_conn.disconnect()
                    except:
                        pass
                    dev_queue.task_done()
                    break
                else:
                    attempts -= 1
                    print(f"{dev.hostname:25}{dev.ip_address:17}connection failed: {err_msg}")
                    time.sleep(5)


def connect(my_username, my_password, dev_queue, settings):

    dev = dev_queue.get()
    ssh_conn = ConnectHandler(device_type=dev.os_type, ip=dev.ip_address,
                                username=my_username, password=my_password)
    del_squeeze_copy(dev, ssh_conn, settings)
    ssh_conn.disconnect()
    dev_queue.task_done()
    

#######################################################################################
# ------------------------------ main part -------------------------------------------#
#######################################################################################

start_time = datetime.now()
current_date = start_time.strftime("%Y.%m.%d")
current_time = start_time.strftime("%H.%M")
log_folder = Path(f"{Path.cwd()}/logs/{current_date}/")  # current dir / logs / date /
log_folder.mkdir(exist_ok=True)

argv_dict = get_argv(argv)
username, password = get_user_pw()
devices = get_devinfo()
total_devices = len(devices)
q = queue.Queue()

print()
print("-------------------------------------------------------------------------------------------------------")
print("hostname                 ip address       comment")
print("-------------------------------------------------------------------------------------------------------")

for flow in range(argv_dict["maxth"]):
    #th = Thread(target=connect, args=(username, password, q, argv_dict))
    th = Thread(target=connect_dev, args=(username, password, q, argv_dict))
    th.daemon = True
    th.start()

for device in devices:
    q.put(device)

q.join()

failed_connection_count, errors_count = write_logs(devices, log_folder, argv_dict)
duration = datetime.now() - start_time

print()
print("-------------------------------------------------------------------------------------------------------")
print(f"total device number: {total_devices}")
print(f"failed connection: {failed_connection_count}  errors: {errors_count}")
print(f"elapsed time: {duration}")
print("-------------------------------------------------------------------------------------------------------\n")
