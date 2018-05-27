# coding=utf-8
'''
Created on 2018年5月5日
@author: heguofeng
'''
from pp_control import PPNetApp
from pp_link import PP_APPID, BroadCastId, wait_available, do_wait,  ip_itos, ip_stoi
from tuntap import TunTap 
from _thread import start_new_thread
import logging
import socket
import time
import hashlib
import struct
from collections import namedtuple
import threading


'''
vpn config:
    vlanid:  100
    iprange: 192.168.1.0-192.168.1.255  (turn to int)
    vlan_secret: b"12345678"
    
vpn function:
auth   vlan_token=mac(vlanid,node_id,secret,sequence)
ip_req(vlan_id,vlan_token,mynode_id,myip(optional))  broadcast on net,wait reply .
   node receive ip_req, 
       if self vlan:
            send ip_res , 
       elif public:
           broadcast to peers 
        
ip_res(vlan_id,vlan_token,status,available_ips(optional))
    if req given ip,check it is available to it,if ok , res ok to reqer,else res error to reqer
    if req has no ip, res min ip available to peer 
    vlan should has {ip:(node_id,last_active,type)} type is static 
    同时广播 arp_res(ip,node_id)  broadcast to vlan peer
    
arp
    arp_req(ip)   寻找ip对应的node_id,在vlan范围内broadcast 
        收到 req，如果在自己记录中，则发送arp_res(),不再则继续广播 
    arp_res(ip,node_id)   
        收到 res  记录对应信息，
        
switch
    分析报文中的目的IP。建立和目的IP的连接，发送数据。
    connect(ip)  建立连接,并监听数据
    send(ip,data) 如果没有建立连接，先connect(ip)

    和tuntap交换数据


'''
EXPIRE_TIME = 24*60*60*1000
TIME_WINDOW = 100
IPInfo = namedtuple("IPInfo",['node_id',"expire"])

class VPNBase(object):
    '''
    connect_peer should define by outside
    '''

    def __init__(self,ip="0.0.0.0",mask="255.255.255.0"):
        self.ip = ip
        self.mask = mask
        self.quitting = True
        self.peer_sock = {}   # {"192.168.1.2":sock}
        self.tun = None

    def start(self):
        self.quitting = False
        self.tun =  TunTap(nic_type="Tun",nic_name="tun0")
        if not self.tun:
            logging.warning("create tap device failure!")
            return
        self.config(self.ip,self.mask)

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        for ip in list(self.peer_sock.keys()):
            if self.peer_sock[ip]:
                self.peer_sock[ip].close()
        if self.tun:
            self.tun.close()
        logging.info("vpn quit!")
    
    def config(self,ip,mask):
        if (ip,mask) == (self.ip,self.mask):
            return 
        self.ip=ip
        self.mask = mask
        if not self.ip == "0.0.0.0" and self.tun:
            self.tun.config(self.ip,self.mask)
            start_new_thread(self.listen, ())
            print("vpn start with ip %s"%self.ip)

    def get_dst(self,data):
        return socket.inet_ntoa(data[16:20])
        
    def set_peersock(self,ip,peer_sock):
        '''
        ip string = "192.168.22.1"
        '''
        self.peer_sock[ip] = peer_sock
        if peer_sock:
            start_new_thread(self.receive_peer,(ip,peer_sock,))
        
    def connect(self,dst_ip):
        logging.warning("I don;t know how to connect!")
        return None

    def listen(self):
        while not self.quitting:
            try:
                data = self.tun.read()
                if data:
                    if not data[0]&0xf0 ==0x40:
                        continue
                    dst_ip = self.get_dst(data)                    
#                     logging.debug("rev %d %s \n%s"%(len(data),dst_ip,''.join('{:02x} '.format(x) for x in data)))

                    if dst_ip not in self.peer_sock:
                        sock = self.connect(dst_ip)
                        if sock:
                            self.set_peersock(dst_ip,sock)
                    if dst_ip in self.peer_sock and self.peer_sock[dst_ip]:
                        self.peer_sock[dst_ip].sendall(data)
#                     if data[9] == 0x06:
#                         logging.debug("send %d \n%s"%(len(data),''.join('{:02x} '.format(x) for x in data)))
            except OSError as exps:
                logging.warning(exps)
                break
            except Exception as exp:
                logging.warning(exp)
                pass
        self.quit()

    def receive_peer(self,ip,peer_sock):
        while not self.quitting:
            try:
                data = peer_sock.recv(1522)
                # logging.debug("receive %s"%''.join('{:02x} '.format(x) for x in data))
                if data :
                    n= self.tun.write(data)
#                     logging.debug("write %d %d \n %s"%(n,len(data),''.join('{:02x} '.format(x) for x in data)))
                else:
                    continue
            except socket.timeout:
                continue
            except OSError as exps:
                if ip in self.peer_sock:
                    self.peer_sock.pop(ip)
                logging.warning(exps)
                break
            except Exception as exp:
                logging.warning(exp)
                pass


class PPVPN(PPNetApp):
    '''
    vpn is a special proxy
    
    config = { 
            Vlan:100,
            IPRange: {start:100,end:200},
            VlanIP: 192.168.1.3
            VlanMask: 255.255.255.0,
            VlanSecret:12345678
    
    }
    '''
    class VPNMessage(PPNetApp.AppMessage):
        def __init__(self,**kwargs):
            tags_id={"ip_req":1,"ip_res":2,"arp_req":3,"arp_res":4,"connect_req":5,"connect_res":6,
                     "session_src":11,"session_dst":12,"session_id":13,"ip":14,"node_id":15,"token":16,"salt":17,"vlan_id":18}
            parameter_type = {
                              11:"I",12:"I",13:"I",14:"I",15:"I",17:"I",18:"I"}
            super().__init__( app_id=PP_APPID["VPN"],
                            tags_id=tags_id,
                            parameter_type=parameter_type,**kwargs)

    def __init__(self,station,config):
        
        super().__init__(station=station,app_id= PP_APPID["VPN"] )
        self.vlan_id = config["VlanId"]
        self.secret = config["VlanSecret"].encode()        
        self.ip_range = config.get("IPRange",{"start":"192.168.33.1","end":"192.168.33.255"})
#         self.ip_range = {"start":ip_stoi(ip_range["start"]),"end":ip_stoi(ip_range["end"])}
        self.ip = config.get("VlanIP","0.0.0.0")
        self.mask = config.get("VlanMask","255.255.255.0")

        self.is_running = False
        self.vlan_table = {}  #{ip:(node_id,last_active)
        self.vpn = None
#         self.ip = ip_stoi(ip)
#         self.mask = mask

    def start(self):
        super().start()
        self.check()
        if not self.station.testing:
            self.start_vpn()
        return self
    
    def quit(self):
        self.stop_vpn()
        super().quit()

    def check(self):
        if not self.is_running:
            self.ip_req(BroadCastId)
#             start_new_thread(do_wait,(lambda :self.ip_req(BroadCastId),lambda: not self.ip=="0.0.0.0",3))
        self.timer = threading.Timer(60, self.check)
        self.timer.start()
        
    def start_vpn(self):
        if self.vpn:
            if not self.vpn.quitting:
                self.vpn.quit()
        logging.debug("%d init vpn with ip %s" %(self.station.node_id,self.ip))
        self.vpn = VPNBase()
        self.vpn.connect = self._connect
        self.vpn.start()
        if not self.ip == "0.0.0.0":
            self.set_ip(self.ip, self.mask)
 
    def stop_vpn(self):
        if self.vpn:
            self.vpn.quit()
        self.is_running = False

    def set_ip(self,ip,mask="255.255.255.0"):
        ok,_ = self._verify_ip(self.station.node_id, ip)
        if ok:
            self.ip = ip
            self.mask = mask
        else:
            return
        logging.info("%d  set vpn ip %s"%(self.station.node_id,self.ip))
        if not self.ip=="0.0.0.0" :
            self.is_running = True
            self._setARP(self.station.node_id, self.ip)
            self.arp_cast()
            if self.vpn:
                self.vpn.config(ip,mask)
        else:
            self.is_running = False

                
    def _connect(self,ip):
        if not (ip_stoi(self.ip_range["start"]) <= ip_stoi(ip) <= ip_stoi(self.ip_range["end"])):
#             logging.debug("not valid vlan ip start %s %d"%(self.ip_range,ip))
            return 
        if ip not in self.vlan_table:
            node_id = self.wait_arp_req(ip)
        else:
            node_id = self.vlan_table[ip].node_id
        if node_id:
            session = self.station.flow.connect(peer_id=node_id)
            logging.info("session %s %s",session,self.station.flow.sessions)
            if session in self.station.flow.sessions and self.station.flow.sessions[session][0]:
                self.connect_req(session,self.ip)
                return self.station.flow.sessions[session][0]
            else:
                print("can't connect vpn peer!")
        else:
            logging.warning("can't get vpn peer")             

    def _getToken(self,node_id,salt):
        md5obj = hashlib.md5()
        md5obj.update(struct.pack("I",salt))
        md5obj.update(self.secret)
        md5obj.update(struct.pack("I",node_id))
        md5obj.update(struct.pack("I",self.vlan_id))
        return md5obj.digest()[:4]
    
    def _verify_msg(self,vpn_msg):
        if vpn_msg.get_parameter("vlan_id") == self.vlan_id:
            timestamp = vpn_msg.get_parameter("salt")
            if TIME_WINDOW*(-1) < int(time.time()) - timestamp < TIME_WINDOW:  
                if vpn_msg.get_parameter("token") == self._getToken(vpn_msg.get_parameter("node_id"), 
                                                                    vpn_msg.get_parameter("salt")):
                    return True
                else:
                    logging.warning("token mismatch %s"%self._getToken(vpn_msg.get_parameter("node_id"), 
                                                                vpn_msg.get_parameter("salt")))
            else:
                logging.warning("not correct timestampe %d %d"%(timestamp,int(time.time())))
        else:
            logging.debug("self vlan %d peer vlan %d"%(self.vlan_id,vpn_msg.get_parameter("vlan_id")))

        return False    

    def _getFreeIP(self):
        for ip in range(ip_stoi(self.ip_range["start"]),ip_stoi(self.ip_range["end"])):
            sip = ip_itos(ip)
            if sip not in self.vlan_table:
                return sip
            if int(time.time()) > self.vlan_table[sip].expire:
                return sip 
        return '0.0.0.0'
    
    def _verify_ip(self,node_id,ip):
        '''
        return True,ip if ip is OK
        return False,suggest_ip if Failue
        '''
        if ip in self.vlan_table:
            if self.vlan_table[ip].node_id== node_id:
                return True,ip
            elif int(time.time()) > self.vlan_table[ip].expire:
                return True,ip
            else:
                return False,self._getFreeIP()
        else:
            return True,ip
    
    def _lan_cast(self,vpn_msg):
        for ip in self.vlan_table:
            self.send_msg(self.vlan_table[ip].node_id, vpn_msg)
    
    def _lan_forward(self,ppmsg):
        ppmsg.set("ttl",ppmsg.get("ttl")-1)
        src_id = ppmsg.get("src_id")
        for ip in self.vlan_table:
            if not self.vlan_table[ip].node_id in (self.station.node_id,src_id):
                ppmsg.set("dst_id",self.vlan_table[ip].node_id)
                self.station.send_ppmsg(self.station.peers[self.vlan_table[ip].node_id],ppmsg)

    def _setARP(self,node_id,ip):
        '''
        if changed return True
        '''
        if ip in self.vlan_table and self.vlan_table[ip].node_id==node_id:
            return False
        for tip in list(self.vlan_table.keys()):
            ipinfo = self.vlan_table[tip]
            if ipinfo.node_id== node_id or int(time.time())>ipinfo.expire:
                self.vlan_table.pop(tip)
        self.vlan_table[ip] = IPInfo(node_id,int(time.time())+EXPIRE_TIME)
        return True                

    
    def arp_cast(self):
        for ip in self.vlan_table:
            self.arp_res(self.vlan_table[ip].node_id)
            
    def _confirm(self,vpn_msg):
        ip = ip_itos(vpn_msg.get_parameter("ip"))
        node_id = vpn_msg.get_parameter("node_id")
        if node_id == self.station.node_id:
            self.set_ip(ip)
        elif ip:
            ok,suggest_ip = self._verify_ip(node_id,ip)
            if ok:
                if self._setARP(node_id,ip):
#                     self._lan_cast(vpn_msg)
                    pass
            else:#error
                self.ip_res(node_id,suggest_ip)
        
    def ip_req(self,node_id):
#         salt = random.randint(0,0xffffffff)
        salt = int(time.time())
        dictdata = {"command":"ip_req",
                    "parameters":{
                        "node_id":self.station.node_id,
                        "token":self._getToken(self.station.node_id,salt),
                        "vlan_id":self.vlan_id,
                        "ip":ip_stoi(self.ip),
                        "salt":salt}}
        logging.debug(dictdata)
        self.send_msg(node_id, PPVPN.VPNMessage(dictdata=dictdata))        

    def ip_res(self,node_id,ip):
        result_ip = 0
        if not ip == "0.0.0.0":
            _,result_ip = self._verify_ip(node_id, ip)
        else:
            #get max 
            result_ip = self._getFreeIP()
            pass
#         salt = random.randint(0,0xffffffff)
        salt = int(time.time())
        dictdata = {"command":"ip_res",
                    "parameters":{
                        "node_id":node_id,
                        "token":self._getToken(node_id,salt),
                        "vlan_id":self.vlan_id,
                        "ip":ip_stoi(result_ip),
                        "salt":salt}}
        logging.debug("set %d ip %s"%(node_id,result_ip))
        if result_ip:
            self._setARP(node_id,result_ip)            
#             self._lan_cast(PPVPN.VPNMessage(dictdata=dictdata))
            self.arp_res(node_id)      # tell peer self arp      
            self.send_msg(node_id, PPVPN.VPNMessage(dictdata=dictdata))

    def arp_req(self,ip):
#         salt = random.randint(0,0xffffffff)
        salt = int(time.time())
        dictdata = {"command":"arp_req",
                    "parameters":{
                        "node_id":self.station.node_id,
                        "token":self._getToken(self.station.node_id,salt),
                        "vlan_id":self.vlan_id,
                        "ip":ip_stoi(ip),
                        "salt":salt}}
        self._lan_cast(PPVPN.VPNMessage(dictdata=dictdata)) 
           
    def arp_res(self,req_node_id):
#         salt = random.randint(0,0xffffffff)
        salt = int(time.time())
        dictdata = {"command":"arp_res",
                    "parameters":{
                        "node_id":self.station.node_id,
                        "token":self._getToken(self.station.node_id,salt),
                        "vlan_id":self.vlan_id,
                        "ip":ip_stoi(self.ip),
                        "salt":salt}}
        self.send_msg(req_node_id,PPVPN.VPNMessage(dictdata=dictdata))       

        
    def wait_arp_req(self,ip):
        self.arp_req(ip) 
        ipnode = wait_available(self.vlan_table,ip,3)
        if ipnode:
            return ipnode[0]
        else:
            return 0
               
    def connect_req(self,session,ip):
        dictdata = {"command":"connect_req",
                    "parameters":{
                      "session_src":session[0],
                      "session_dst":session[1],
                      "session_id":session[2],
                      "ip":ip_stoi(ip)}}
        logging.debug(dictdata)
        self.send_msg(session[1], PPVPN.VPNMessage(dictdata=dictdata))
        return

    def connect_res(self,session,ip):
        dictdata = {"command":"connect_res",
                    "parameters":{
                      "session_src":session[0],
                      "session_dst":session[1],
                      "session_id":session[2],
                      "ip":ip_stoi(ip)}}
        logging.debug(dictdata)
        self.send_msg(session[0], PPVPN.VPNMessage(dictdata=dictdata))
        return


        
    def process(self,ppmsg,addr):
        vpn_msg = PPVPN.VPNMessage(bindata=ppmsg.get("app_data"))
        logging.debug("%d: receive from %s:%d   %s"%(self.station.node_id,addr[0],addr[1],vpn_msg.dict_data))
        command = vpn_msg.get("command")
        
        node_id = ppmsg.get("src_id")
        if command == "ip_req":
            if self._verify_msg(vpn_msg):
                self.ip_res(node_id,ip_itos(vpn_msg.get_parameter("ip")))
        if command in ( "ip_res","arp_res"):
            if self._verify_msg(vpn_msg):
                self._confirm(vpn_msg)
        if command == "arp_req":
            if self._verify_msg(vpn_msg):
                if ip_itos(vpn_msg.get_parameter("ip")) == self.ip:
                    self.arp_res(vpn_msg.get_parameter("node_id"))
                else:
                    self._lan_forward(ppmsg)
  
        if command in ("connect_req","connect_res"):
            session = (vpn_msg.get_parameter("session_src"),vpn_msg.get_parameter("session_dst"),vpn_msg.get_parameter("session_id"))
            if not (session in self.station.flow.sessions and self.station.flow.sessions[session][0]):
                logging.warning("not connect , can't start vpn!")
                return
             
        if command == "connect_req":
            if session in self.station.flow.sessions and self.station.flow.sessions[session][0]:
                self.vpn.set_peersock(ip_itos(vpn_msg.get_parameter("ip")),self.station.flow.pop_session(session))
            self.connect_res(session,self.ip)
        if command == "connect_res":
            if session in self.station.flow.sessions and self.station.flow.sessions[session][0]:
                self.vpn.set_peersock(ip_itos(vpn_msg.get_parameter("ip")),self.station.flow.pop_session(session))
                
#             self.connect(node_id)


    def run_command(self, command_string):
        cmd = command_string.split(" ")
        if cmd[0] in ["stat","vpn"]:
            if cmd[0] =="stat":
                print("vpn %s ip: %s"%("is runing " if self.vpn and not self.vpn.quitting else "not run",
                                       self.ip))
            if cmd[0] =="vpn" and len(cmd)>=3  and cmd[1]=="ip":
                print("vpn ip set to %s "%(cmd[1]))
                self.set_ip(cmd[2])
                
            if cmd[0] =="vpn" and len(cmd)>=3 and cmd[1]=="ipreq":
                self.ip_req(int(cmd[2]))
                time.sleep(1)
                self.run_command("vpn detail")
            if cmd[0] =="vpn" and len(cmd)>=3 and cmd[1]=="arp":
                self.arp_req(cmd[2])
                time.sleep(1)
                print(self.vlan_table) 
            if cmd[0] =="vpn" and len(cmd)>=3 and cmd[1]=="connect":
                if self.vpn:
                    self._connect(cmd[2])
                time.sleep(1)
                self.run_command("vpn detail")              
            if cmd[0] =="vpn" and len(cmd)>=2  and cmd[1]=="detail":
                print("vpn %d %s ip: %s"%(self.vlan_id, "is runing " if self.vpn and not self.vpn.quitting else "not run",
                                       self.ip))                
                print(self.vlan_table)
                if self.vpn:
                    print(self.vpn.peer_sock)


            return True
        return False
    pass

