# autobase.py: automatically configure F9P as base station with updated position from RTK solution
#
#      python3 autobase.py 

import os, sys, subprocess, signal
import time
import re
import socket
import RPi.GPIO as GPIO
from statistics import median

# Define output stream in RTKLIB format
#stream_out = 'ntrips://:BETATEST@www.rtk2go.com:2101/niwot_f9p'    # NTRIP example
stream_out = 'tcpsvr://:5000'                                       # TCP/IP example for port 5000

# Receiver command files
cmd_file_template = 'base_template.cmd' 
base_cmd_file = 'base.cmd'
rover_cmd_file = 'rover.cmd'

# Time constants
max_wait = 10 * 60  # max wait for fix in seconds
fix_time = 3 * 60   # required fix time in seconds for position fix

# TCP/IP defines
TCP_PORT = 5001
TCP_IP = '127.0.0.1'
BUFFER_SIZE = 4096

# define GPIO by pin #
led = 21 
button = 23  

# ----------- Function defines ------------------------------------

def get_GGA_msg(sock):
	while (1):
		data = sock.recv(BUFFER_SIZE)

		if not data: 
			print('get_GGA: No data in buffer')
			break
		try:
			ix = data.find(b'GGA,')
			if ix != -1:
				data = str(data[ix:], 'utf-8')
				msg = data.split(',')
				if len(msg) > 11:
					break
				else:
					print('get_GGA: Partial message')
		except:
			print('get_GGA: error reading message')
	try:
		fix = int(msg[6])
		lat = float(msg[2])
		lat1 = int(lat / 100)
		lat = lat1 + (lat - lat1 * 100) / 60
		lon = float(msg[4])
		lon1 = int(lon / 100)
		lon = -(lon1 + (lon - lon1 * 100) / 60) 
		hgt = float(msg[9]) + float(msg[11]) # remove geoid offset to get ellipsoid height
		# TO DO: check for signs of lat and lon
	except:
		print('Error parsing GGA data')
		return(0, 0, 0, 0)

	return(lat, lon, hgt, fix)

def blink_LED(total_time, cycle_time):
	num_cycles = round(total_time / cycle_time)
	for n in range(num_cycles):
		GPIO.output(led, GPIO.HIGH)
		time.sleep(cycle_time / 2)
		GPIO.output(led, GPIO.LOW)
		time.sleep(cycle_time / 2)

def button_status():
	return GPIO.input(button)


# ---------- Start of main code --------------------------------


# Get input stream from config file in RTKLIB format
f = open('/boot/ntrip_in.txt')
ntrip_in = f.read().rstrip()
f.close()
print(ntrip_in)
#ntrip_in = ':niwot@www.rtk2go.com:2101/niwot_m8t'  # Example of config file contents

# initialize LED and switch
GPIO.setwarnings(False) 
GPIO.setmode(GPIO.BOARD) # Use header pin #s
GPIO.setup(led, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(button, GPIO.IN,GPIO.PUD_UP) 

# find USB tty name
cp =subprocess.check_output('ls /dev/ttyAC*', shell=True)
usb_tty = chr(cp[-2])

# create RTKLIB STR2STR command lines
str2str_cmd1 = 'str2str -in serial://ttyACM' + usb_tty + ':115200 -out tcpsvr://:5001 -c ' + rover_cmd_file + ' > str2str1.log'
# str2str_cmd_2 defined inline
str2str_cmd3 = 'str2str -in serial://ttyACM' + usb_tty + ':115200 -out ' + stream_out  + ' -c ' + base_cmd_file + ' > str2str3.log'

while True:  # main loop

	# Wait for push button, if push button pressed for 5 seconds, shut Pi down
	press = 0
	while 0: #True:
		blink_LED(1, 1)
		if button_status() == 0:
			GPIO.output(led, GPIO.HIGH)
			start = time.time()
			while True:
				time.sleep(1)
				if time.time() - start > 5:
					GPIO.output(led, GPIO.LOW)
				if button_status() == 1:
					break
			press = time.time() - start
			break
	if press >= 5:
		break	# shutdown

	# Use stream server to configure recevier for rover mode and get approximate receiver location
	print('\nConfigure receiver for rover mode ...\n')
	print(str2str_cmd1)
	cp = subprocess.Popen(str2str_cmd1, shell=True,preexec_fn=os.setsid)
	if cp == 0:
		print('Stream server failed to start')
		break  # exit main loop
	blink_LED(3, 0.5)

	# open TCP port
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.connect((TCP_IP, TCP_PORT))
	except:
		print('Error: Failed to open TCP/IP port')
		os.killpg(os.getpgid(cp.pid), signal.SIGTERM)
		break  # exit main loop

	blink_LED(2, 0.5)

	nsec = 0
	while nsec < 30:
		lat, lon, hgt, fix = get_GGA_msg(sock)
		print('%d, %d, %.7f %.7f %.3f' % (t_fix, fix, lat, lon, hgt))
		if lat != 0.0:   # check for valid measurement
			break
		blink_LED(1, 0.5)
		nsec += 1
	if lat == 0.0:
		print('no valid GGA messages')
		break

	print('Stop stream server')
	# close stream server
	os.killpg(os.getpgid(cp.pid), signal.SIGTERM)
	sock.close()  # close TCP port
	time.sleep(0.5)
	
	# start STR2STR process to stream NTRIP base observations to F9P, F9P output will go to TCP port
	print('\nStart NTRIP->F9P stream ...\n')
	str2str_cmd2 = 'str2str -in ntrip://%s -n 2000 -p %.7f %.7f %.2f  -out serial://ttyACM%s:115200#%s> str2str2.log' % (ntrip_in, lat, lon, hgt, usb_tty, str(TCP_PORT))
	print(str2str_cmd2)
	cp = subprocess.Popen(str2str_cmd2, shell=True,preexec_fn=os.setsid)
	if cp == 0:
		print('Stream server failed to start')
		break  # exit main loop
	else:
		blink_LED(5, 0.25)
	
	# open TCP port
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.connect((TCP_IP, TCP_PORT))
	except:
		print('Error: Failed to open TCP/IP port')
		os.killpg(os.getpgid(cp.pid), signal.SIGTERM)
		break  # exit main loop
	
	# monitor TCP port for fix
	t_fix = 0
	lat_list = []
	lon_list = []
	hgt_list = []
	for t_total in range(max_wait):
		if button_status() == 0:
			break
		lat, lon, hgt, fix = get_GGA_msg(sock)
		print('%d, %d, %.7f %.7f %.3f' % (t_fix, fix, lat, lon, hgt))
		if fix == 4:  # check for fix
			lat_list.append(lat)
			lon_list.append(lon)
			hgt_list.append(hgt)
			if t_fix > fix_time:
				break
			t_fix +=1
			blink_LED(1, 0.125)
		else:
			blink_LED(1, 0.25)

	if t_total >= max_wait or t_fix < fix_time:
		print('Error: Unable to get fix')
		os.killpg(os.getpgid(cp.pid), signal.SIGTERM)
		while button_status == 0:  # wait for button release
			pass
		continue  # skip rest of code and wait for button push

	# calculate measured position
	lat = median(lat_list)
	lon = median(lon_list)
	hgt = median(hgt_list)
	print('\nMeasured position = %.7f, %.7f, %.3f\n' % (lat, lon, hgt))
	GPIO.output(led, GPIO.HIGH) # turn on LED
	
	# close stream server and TCP port
	print('Close stream and port ...\n')
	sock.close()  # close TCP port
	os.killpg(os.getpgid(cp.pid), signal.SIGTERM)
	
	# modify receiver command file to include updated position
	fid_in = open(cmd_file_template,"r")
	fid_out = open(base_cmd_file,"w")
	cmd_list = fid_in.read()
	
	# insert position into template
	lat_string = str(round(lat * 1e7)).zfill(10)
	lon_string = str(round(lon * 1e7)).zfill(10)
	hgt_string = str(round(hgt * 1e2)).zfill(4)
	cmd_list = cmd_list.replace('0000000000', lat_string, 1)
	cmd_list = cmd_list.replace('0000000000', lon_string, 1)
	cmd_list = cmd_list.replace('0000000000', hgt_string, 1)
	
	# save result to receiver command file
	fid_out.write(cmd_list)
	fid_in.close()
	fid_out.close()
	
	# start STR2STR process to stream F9P observations to NTRIP server
	print('\nSTR2STR F9P->NTRIP stream started ...\n')
	print(str2str_cmd3)
	cp = subprocess.Popen(str2str_cmd3, shell=True,preexec_fn=os.setsid)
	if cp == 0:
		print('Stream server failed to start')
		break  # exit main loop

	
	# Wait for push button, if push button pressed for 5 seconds, shut Pi down
	# else go back to standby mdode
	while True:
		if button_status() == 0:
			start = time.time()
			while True:
				time.sleep(1)
				if time.time() - start > 5:
					GPIO.output(led, GPIO.LOW)
				if button_status() == 1:
					break   # button released
			press = time.time() - start
			os.killpg(os.getpgid(cp.pid), signal.SIGTERM)  # kill str2str
			break   # exit button loop
	if press >= 5:
		break	# shutdown

	
		

GPIO.output(led, GPIO.LOW)
time.sleep(5)
print('\nShutdown ....')
os.system('cp autobase.log autobase_prev.log') 
os.system('sudo killall str2str')
os.system('sudo poweroff')



