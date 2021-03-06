import yaml
import time
import os
import queue
import math
from pprint import pformat
from threading import Thread
from getpass import getpass
from sys import argv
from datetime import datetime, timedelta
from netmiko import ConnectHandler
from netmiko.ssh_exception import NetMikoTimeoutException


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
        self.logging = []
        self.vendor_cisco = False
        self.vendor = []
        self.error = False
        self.error_msg = []

    def reset(self):
        self.connection_status = True  # failed connection status, False if connection fails
        self.connection_error_msg = ""  # connection error message

        self.ios_list = []
        self.logging = []
        self.vendor_cisco = False
        self.vendor = []
        self.error = False
        self.error_msg = []
        

#######################################################################################
# ---------------------------------- common part -------------------------------------#
#######################################################################################

def get_argv(arguments):
    settings = {"maxth": 20,
                "del_old_ios": False,
                "squeeze": False,
                "copy": False,
                "del4": False}

    for arg in arguments:
        if arg.startswith("mt"):
            settings["maxth"] = int(arg.split("mt")[-1])
        elif arg == "del":
            settings["del_old_ios"] = True
        elif arg == "squeeze":
            settings["squeeze"] = True
        elif arg == "copy":
            settings["copy"] = True
        elif arg == "del4":
            settings["del4"] = True    
        elif arg == "all":
            settings["del_old_ios"] = True
            settings["squeeze"] = True
            settings["copy"] = True

    print()
    print(f"max threads:...................{settings['maxth']}\n"
          f"delete old IOS:................{settings['del_old_ios']}\n"
          f"squeeze FLASH:.................{settings['squeeze']}\n"
          f"copy IOS, save BOOT:...........{settings['copy']}\n"
          f"delete 15.4(3)S4:..............{settings['del4']}\n")

    return settings


def get_user_pw():
    user = input("Enter login: ")
    psw = getpass()

    return user, psw


def get_devinfo():
    devs = []
    with open("devices.yaml", "r") as file:
        devices_info = yaml.load(file, yaml.SafeLoader)
        for hostname, ip_address in devices_info.items():
            dev = CellSiteGateway(ip=ip_address, host=hostname)
            devs.append(dev)

    print()
    return devs


def write_logs(devs):
    
    failed_connection = 0
    errors = 0

    timenow = datetime.now()
    current_date = timenow.strftime("%Y.%m.%d")
    current_time = timenow.strftime("%H.%M.%S")

    folder = f"logs/{current_date}"

    if not os.path.exists(folder):
        os.mkdir(folder)

    err_msg_file = open(f"{folder}/{current_time}_connection_error_msg.txt", "w")
    err_msg_file.write(f"{current_date} {current_time}\n\n")

    log_file = open(f"{folder}/{current_time}_logs.txt", "w")
    log_file.write(f"{current_date} {current_time}\n\n")

    error_file = open(f"{folder}/{current_time}_error_logs.txt", "w")
    error_file.write(f"{current_date} {current_time}\n\n")

    vendor_file = open(f"{folder}/{current_time}_sfp_vendor.txt", "w")
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

            vendor_file.write(f"{dev.hostname} : {dev.ip_address}\t{pformat(dev.vendor)}\n")

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

    return failed_connection, errors


#######################################################################################
# ------------------------------ def         -----------------------------------------#
#######################################################################################


def count_duration(dev_number, threads, start):
    squeeze = 17
    copy = 6
    additional_time = 1
    rounds = math.ceil(dev_number/threads)
    duration_time = (squeeze + copy) * rounds + additional_time

    endtime = start + timedelta(minutes=duration_time)
    print(f'approximate duration: {duration_time} minutes, end time: {endtime.strftime("%Y.%m.%d %H:%M:%S")}')


def show_commands(dev, connection):
    dirflash = connection.send_command(r"dir flash:")
    for line in dirflash.splitlines():
        if line.endswith(".bin"):
            dev.ios_list.append(line.split()[-1])


def controller(dev, connection):
    show_uplink = connection.send_command(r"show interfaces description | include UPLINK|pagg")
    uplink = ["pagg", "UPLINK"]
    ports = []
    for line in show_uplink.splitlines():
        if any([i in line for i in uplink]):
            ports.append(line.split()[0])

    for port in ports:
        show_controller = connection.send_command(f"show controllers {port} | include vendor_name")
        for i in show_controller.splitlines():
            if "vendor_name" in i:
                dev.vendor.append(i.split()[-1])
                if "CISCO" in i:
                    dev.vendor_cisco = True


def delete_old_ios_1543s4(dev, connection, settings):
    if settings["del4"]:
        version = connection.send_command(r"show version | include Software")
        new_ios = ["asr901-universalk9-mz.154-3.S4.bin", "asr901-universalk9-mz.156-2.SP7.bin"]
        if all([ios in dev.ios_list for ios in new_ios]):
            if "Version 15.6(2)SP7" in version:
                dev.logging.append(connection.send_command(f"delete flash:asr901-universalk9-mz.154-3.S4.bin",
                                                           expect_string=r"Delete filename",
                                                           strip_command=False, strip_prompt=False))
                dev.logging.append(connection.send_command("", expect_string=r"confirm",
                                                           strip_command=False, strip_prompt=False))
                dev.logging.append(connection.send_command("", expect_string=r"#",
                                                           strip_command=False, strip_prompt=False))
            else:
                print(f"{dev.hostname:25}{dev.ip_address:17}ios version is not 15.6(2)SP7")
        else:
            print(f"{dev.hostname:25}{dev.ip_address:17}{new_ios} are not in flash memory")


def delete_old_ios(dev, connection, settings):
    new_ios = ["asr901-universalk9-mz.154-3.S4.bin", "asr901-universalk9-mz.156-2.SP7.bin"]
    old_ios = [ios for ios in dev.ios_list if ios not in new_ios]
    left_ios = [ios for ios in dev.ios_list if ios in new_ios]

    if old_ios:
        if settings["del_old_ios"]:
            for ios in old_ios:
                dev.logging.append(connection.send_command(f"delete flash:{ios}", expect_string=r"Delete filename",
                                                           strip_command=False, strip_prompt=False))
                dev.logging.append(connection.send_command("", expect_string=r"confirm",
                                                           strip_command=False, strip_prompt=False))
                dev.logging.append(connection.send_command("", expect_string=r"#",
                                                           strip_command=False, strip_prompt=False))

            print(f"{dev.hostname:25}{dev.ip_address:17}deleted: {old_ios}, left: {left_ios}")
        else:
            print(f"{dev.hostname:25}{dev.ip_address:17}old ios left: {old_ios}")
    if not left_ios:
        print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] no new ios left")
        dev.error = True
        dev.error_msg.append("no new ios left")

    if settings["squeeze"]:
        squeeze_start = datetime.now()
        dev.logging.append(connection.send_command("squeeze flash:", expect_string=r"confirm",
                                                   strip_command=False, strip_prompt=False))
        squeeze_log = connection.send_command("", expect_string=r"#", delay_factor=15,
                                              strip_command=False, strip_prompt=False)
        dev.logging.append(squeeze_log)
        squeeze_duration = datetime.now() - squeeze_start
        if "Squeeze of flash complete" in squeeze_log:
            print(f"{dev.hostname:25}{dev.ip_address:17}squeeze complete, duration: {squeeze_duration}")
        else:
            print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] squeeze error")
            dev.error = True
            dev.error_msg.append("squeeze error")

    if settings["copy"]:
        if dev.vendor_cisco:
            copy_start = datetime.now()
            dirflash_free = connection.send_command(r"dir flash: | in free")
            free_space = 0
            for line in dirflash_free.splitlines():
                if line.endswith(r"bytes free)"):
                    free_space = int(line.split()[-3][1:])

            if "asr901-universalk9-mz.156-2.SP7.bin" in dev.ios_list:
                print(f"{dev.hostname:25}{dev.ip_address:17}new ios already in flash memory")
            else:
                if free_space > 46000000:
                    dev.logging.append(connection.send_command("copy ftp://212.19.149.62/mbh/"
                                                               "asr901-universalk9-mz.156-2.SP7.bin flash:",
                                                               expect_string=r"Destination filename",
                                                               strip_command=False, strip_prompt=False))
                    dev.logging.append(connection.send_command("", expect_string=r"#",
                                                               strip_command=False, strip_prompt=False,
                                                               delay_factor=15))
                else:
                    print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] no free space: {free_space}")
                    dev.error = True
                    dev.error_msg.append(f"no free space: {free_space}")

            md5_log = connection.send_command("verify /md5 asr901-universalk9-mz.156-2.SP7.bin",
                                              strip_command=False, strip_prompt=False,
                                              delay_factor=15)
            dev.logging.append(md5_log)

            if "5981f0cc5a76b85a7c6643d0d2b7470a" in md5_log:
                new_boot = ["no boot system", "boot system flash asr901-universalk9-mz.156-2.SP7.bin"]
                dev.logging.append(connection.send_config_set(new_boot, strip_command=False, strip_prompt=False))
                dev.logging.append(connection.save_config())

                '''
                try:
                    dev.logging.append(connection.save_config())
                except IOError as commit_msg:
                    dev.logging.append(connection.send_command("write", expect_string="confirm",
                                                               strip_command=False, strip_prompt=False))
                    dev.logging.append(connection.send_command("", expect_string=r"#",
                                                               strip_command=False, strip_prompt=False))
                    print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] write -> confimg -> OK: {commit_msg}")
                except Exception as commit_msg_2:
                    print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] commit error: {commit_msg_2}")
                    dev.error = True
                    dev.error_msg.append("commit error")
                '''

                copy_duration = datetime.now() - copy_start
                print(f"{dev.hostname:25}{dev.ip_address:17}md5 checksum is ok, new boot is configured, "
                      f"duration: {copy_duration}")
            else:
                print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] md5 checksum failed")
                dev.error = True
                dev.error_msg.append("md5 checksum failed")

        else:
            print(f"{dev.hostname:25}{dev.ip_address:17}[ERROR] uplink sfp transceiver vendor is not cisco")
            dev.error = True
            dev.error_msg.append("uplink sfp transceiver vendor is not cisco")

#######################################################################################
# ------------------------------ multithreading part ---------------------------------#
#######################################################################################


def connect_dev(my_username, my_password, dev_queue, settings):
    while True:
        dev = dev_queue.get()
        attempts = 3
        while True:
            try:
                # print(f"{dev.hostname:25}{dev.ip_address:17}")
                ssh_conn = ConnectHandler(device_type=dev.os_type, ip=dev.ip_address,
                                          username=my_username, password=my_password)

                show_commands(dev, ssh_conn)
                controller(dev, ssh_conn)
                delete_old_ios(dev, ssh_conn, settings)
                delete_old_ios_1543s4(dev, ssh_conn, settings)

                ssh_conn.disconnect()
                dev_queue.task_done()
                break

            except NetMikoTimeoutException as err_msg:
                dev.connection_status = False
                dev.connection_error_msg = str(err_msg)
                print(f"{dev.hostname:25}{dev.ip_address:17}timeout")
                dev_queue.task_done()
                break

            except Exception as err_msg:
                if attempts == 1:
                    dev.connection_status = False
                    dev.connection_error_msg = str(err_msg)
                    print(f"{dev.hostname:25}{dev.ip_address:17}connection failed after all attempts, {err_msg}")
                    try:
                        ssh_conn.disconnect()
                    except Exception as disconnect_err_msg:
                        print(f"{dev.hostname:25}{dev.ip_address:17}disconnect failed in except part, "
                              f"{disconnect_err_msg}")
                    dev_queue.task_done()
                    break
                else:
                    attempts -= 1
                    dev.reset()
                    print(f"{dev.hostname:25}{dev.ip_address:17}connection failed, attempts left: {attempts}, {err_msg}")
                    time.sleep(5)


#######################################################################################
# ------------------------------ main part -------------------------------------------#
#######################################################################################

starttime = datetime.now()

argv_dict = get_argv(argv)
username, password = get_user_pw()

devices = get_devinfo()
total_devices = len(devices)
q = queue.Queue()

count_duration(total_devices, argv_dict["maxth"], starttime)

print()
print("-------------------------------------------------------------------------------------------------------")
print("hostname                 ip address       comment")
print("-------------------------------------------------------------------------------------------------------")


for flow in range(argv_dict["maxth"]):
    th = Thread(target=connect_dev, args=(username, password, q, argv_dict))
    th.setDaemon(True)
    th.start()

for device in devices:
    q.put(device)

q.join()

failed_connection_count, errors_count = write_logs(devices)
duration = datetime.now() - starttime

print()
print("-------------------------------------------------------------------------------------------------------")
print(f"total device number: {total_devices}")
print(f"failed connection: {failed_connection_count}  errors: {errors_count}")
print(f"elapsed time: {duration}")
print("-------------------------------------------------------------------------------------------------------\n")
