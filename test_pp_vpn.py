'''
Created on 2018年5月23日

@author: heguofeng
'''
import unittest
from test.pseudo_net import FakeNet
from pp_link import NAT_TYPE, ip_stoi, set_debug, BroadCastId
from pp_control import PPStation
from pp_flow import Flow, prepare_socket
from pp_vpn import PPVPN, VPNBase
import logging
import time
import socket


class TestVPN(unittest.TestCase):
    
    inited = 0
    quiting = True
    
    def start(self):
        if self.inited == 1:
            return
        self.fake_net = FakeNet()


        self.nodes = {100: { "node_id": 100,"ip": "180.153.152.193", "port": 54330, "net_id":200,"secret": "",},
                 201: { "node_id": 201,"ip": "116.153.152.193", "port": 54330, "net_id":200,"secret": "",},
                 202:  { "node_id": 202,"ip": "116.153.152.193", "port": 54320, "net_id":200,"secret": "",}}
        config={"net_id":200, "node_port":54330,"nat_type":NAT_TYPE["Turnable"],"nodes":self.nodes,"ip":"0.0.0.0",
                "vpn":{"VlanId":100,"VlanSecret":"12345678"}}
        configA = config.copy()
        configA.update({"node_id":100, "node_ip":"118.153.152.193",})
        configB = config.copy()
        configB.update({"node_id":201, "node_ip":"116.153.152.193" })
        configC = config.copy()
        configC.update({"node_id":202, "node_ip":"116.153.152.193" ,"node_port":54320})
        self.stationA = PPStation(configA) 
        self.stationB = PPStation(configB)
        self.stationC = PPStation(configC)
        
        self.fake_net = FakeNet()
        self.fake_net.fake(self.stationA)
        self.fake_net.fake(self.stationB)
        self.fake_net.fake(self.stationC)    
#         self.stationA.beater.beat_interval = 0.1
#         self.stationB.beater.beat_interval = 0.1
#         self.stationB.beater.beat_interval = 0.1
        self.stationA.start()
        self.stationB.start()
        self.stationC.start()           
        
        self.vpnA = PPVPN(self.stationA,config={"VlanId":100,"VlanSecret":"12345678"})   
        self.vpnB = PPVPN(self.stationB,config={"VlanId":100,"VlanSecret":"12345678"})  
#         self.vpnA.testing = True
        self.vpnA.ip = "192.168.33.10"
        self.inited = 1
        
    def quit(self):
        if self.inited:
            self.stationA.quit()
            self.stationB.quit()
            self.stationC.quit()
            self.inited = 0   

    def setUp(self):
        set_debug(logging.DEBUG, "",
                debug_filter=lambda record: record.filename =="pp_vpn.py" or record.filename =="pp_flow.py"  ,
                  )
        self.start()
        pass


    def tearDown(self):
        self.quit()
        pass

#     @unittest.skip("command only")
    def testIPReq(self):
        self.vpnA.start()
        self.vpnB.start()
        time.sleep(3)
        self.vpnB.ip_req(BroadCastId)
        self.assertTrue(not self.vpnB.ip=="0.0.0.0" and self.vpnA.ip=="192.168.33.10","test IP Req")
        self.vpnA.quit()
        self.vpnB.quit()
        pass
    
#     @unittest.skip("command only")
    def testARP(self):
        self.vpnA.start()
        self.vpnB.start()
        time.sleep(1)
        self.vpnA.ip = "192.168.33.10"
#         self.vpnA.vlan_table[self.vpnB.ip]=()
#         self.vpnA.start_vpn()
        self.vpnB.ip = "192.168.33.12"
#         self.vpnB.start_vpn()
        self.vpnA.arp_req(self.vpnB.ip)
        print(self.vpnA.vlan_table)
        time.sleep(1)
        print("vlantable",self.vpnA.vlan_table,self.vpnB.ip)        
        self.assertTrue(self.vpnA.vlan_table[self.vpnB.ip][0]==201,"test ARP")
        self.vpnA.quit()
        self.vpnB.quit()        
        pass
    
    @unittest.skip("need pseudo tcp")
    def testConnect(self):
#         self.stationA.flow = Flow(station=self.stationA,config={"flow_port":7070})
#         self.stationA.services.update({"flow":self.stationA.flow})
#         self.stationB.flow = Flow(station=self.stationB,config={"flow_port":7071})
#         self.stationB.services.update({"flow":self.stationB.flow})
        self.vpnA.start()
        self.vpnB.start()
        time.sleep(1)
        self.vpnA.ip = "192.168.33.10"
        self.vpnB.ip = "192.168.33.12"
        self.vpnA.arp_req(self.vpnB.ip)
        print(self.vpnA.vlan_table)
        time.sleep(1)
        print(self.vpnA.vlan_table,self.vpnB.ip)     
        self.vpnA._connect(self.vpnB.ip)   
        self.assertTrue(self.vpnB.ip in self.vpnA.peer_sock and self.vpnA.vpn.peer_sock,"test connect")
        pass
    
    @unittest.skip("command only")
    def testVPNServer(self):
        vpn = VPNBase("192.168.33.10","255.255.255.0")
        sock = prepare_socket(timeout=10,port=7070)
        sock.listen(10)
        count = 0

        try: #active the port
            sock1 = prepare_socket(timeout=2,port=7070)
            sock1.connect(("100.100.100.100",6000))
        except Exception as exp:
            print(exp)
            pass
        finally:
            sock1.close()

        while count<10:
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                count += 1
                continue
            else:
                print("accept from",conn.getpeername())
                vpn.start()
                vpn.set_peersock("192.168.33.12",conn)
                break

        input("any key to quit!")
        vpn.quit()
        pass

    @unittest.skip("command only")
    def testVPNClient(self):
        vpn = VPNBase("192.168.33.12","255.255.255.0")


        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server=input("server ip,default is 180.153.152.193:")
        if not len(server):
            server = "180.153.152.193"
        print(server)
        count = 0
        while count<10:
            try:
                sock.connect((server,7070))
#                 sock.connect(("180.153.152.193",7070))
            except socket.timeout:
                count += 1
                continue
            else:
                time.sleep(3)
                vpn.start()
                vpn.set_peersock("192.168.33.10",sock)
                break

        input("any key to quit!")
        vpn.quit()
        pass



if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()