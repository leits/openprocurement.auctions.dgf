# -*- coding: utf-8 -*-
import unittest

from openprocurement.api.models import get_now

from openprocurement.auctions.dgf.migration import migrate_data, get_db_schema_version, set_db_schema_version, SCHEMA_VERSION
from openprocurement.auctions.dgf.tests.base import BaseWebTest, BaseAuctionWebTest, test_bids

from uuid import uuid4
from copy import deepcopy


class MigrateTest(BaseWebTest):

    def setUp(self):
        super(MigrateTest, self).setUp()
        migrate_data(self.app.app.registry)

    def test_migrate(self):
        self.assertEqual(get_db_schema_version(self.db), SCHEMA_VERSION)
        migrate_data(self.app.app.registry, 1)
        self.assertEqual(get_db_schema_version(self.db), SCHEMA_VERSION)


class MigrateTestFrom1To2(BaseAuctionWebTest):
    initial_status = 'active.qualification'
    initial_bids = test_bids

    def setUp(self):
        super(MigrateTestFrom1To2, self).setUp()
        migrate_data(self.app.app.registry)
        set_db_schema_version(self.db, 0)

    def test_migrate_one_pending_award(self):
        auction = self.db.get(self.auction_id)
        award = {
            'id': uuid4().hex,
            "bid_id": auction['bids'][1]['id'],
            "status": "pending",
            "complaintPeriod": {
                "startDate": get_now().isoformat(),
            }
        }
        auction['awards'] = [award]
        auction.update(auction)
        self.db.save(auction)
        migrate_data(self.app.app.registry, 1)
        auction = self.app.get('/auctions/{}'.format(self.auction_id)).json['data']
        self.assertEqual(len(auction['awards']), 2)
        self.assertEqual(auction['awards'][0]['status'], 'pending.payment')
        self.assertIn('verificationPeriod', auction['awards'][0])
        self.assertIn('paymentPeriod', auction['awards'][0])
        self.assertEqual(auction['awards'][1]['status'], 'pending.waiting')

        response = self.app.get('/auctions/{}'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data']['status'], u'active.qualification')

        response = self.app.get('/auctions/{}/awards'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(len(response.json['data']), 2)
        self.assertEqual(response.json['data'][0]['status'], u'pending.payment')
        self.assertEqual(response.json['data'][1]['status'], u'pending.waiting')

    def test_migrate_one_active_award(self):
        auction = self.db.get(self.auction_id)
        award = {
            'id': uuid4().hex,
            "bid_id": auction['bids'][1]['id'],
            "status": "active",
            "complaintPeriod": {
                "startDate": get_now().isoformat(),
                "endDate": get_now().isoformat()
            }
        }
        auction['awards'] = [award]
        auction.update(auction)
        self.db.save(auction)
        self.set_status('active.awarded')

        migrate_data(self.app.app.registry, 1)
        auction = self.app.get('/auctions/{}'.format(self.auction_id)).json['data']
        self.assertEqual(len(auction['awards']), 2)
        self.assertEqual(auction['awards'][0]['status'], 'active')
        self.assertIn('verificationPeriod', auction['awards'][0])
        self.assertIn('paymentPeriod', auction['awards'][0])
        self.assertIn('signingPeriod', auction['awards'][0])
        self.assertEqual(auction['awards'][1]['status'], 'pending.waiting')

        response = self.app.get('/auctions/{}'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data']['status'], u'active.awarded')

        response = self.app.get('/auctions/{}/awards'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(len(response.json['data']), 2)
        self.assertEqual(response.json['data'][0]['status'], u'active')
        self.assertEqual(response.json['data'][1]['status'], u'pending.waiting')

    def test_migrate_cancelled_award(self):
        auction = self.db.get(self.auction_id)

        pending_award = {
            'id': uuid4().hex,
            "bid_id": auction['bids'][1]['id'],
            "status": "pending",
            "complaintPeriod": {
                "startDate": get_now().isoformat(),
            }
        }
        cancelled_award = deepcopy(pending_award)
        cancelled_award['id'] = uuid4().hex
        cancelled_award['status'] = 'cancelled'
        cancelled_award['complaintPeriod']['endDate'] = get_now().isoformat()
        auction['awards'] = [cancelled_award, pending_award]

        auction.update(auction)
        self.db.save(auction)
        migrate_data(self.app.app.registry, 1)
        auction = self.app.get('/auctions/{}'.format(self.auction_id)).json['data']

        self.assertEqual(len(auction['awards']), 3)
        self.assertIn('verificationPeriod', auction['awards'][0])
        self.assertEqual(auction['awards'][0]['status'], 'cancelled')
        self.assertEqual(auction['awards'][1]['status'], 'pending.payment')
        self.assertIn('verificationPeriod', auction['awards'][1])
        self.assertIn('paymentPeriod', auction['awards'][1])
        self.assertEqual(auction['awards'][2]['status'], 'pending.waiting')

        response = self.app.get('/auctions/{}'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data']['status'], u'active.qualification')

        response = self.app.get('/auctions/{}/awards'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(len(response.json['data']), 3)
        self.assertEqual(response.json['data'][0]['status'], u'cancelled')
        self.assertEqual(response.json['data'][1]['status'], u'pending.payment')
        self.assertEqual(response.json['data'][2]['status'], u'pending.waiting')

    def test_migrate_pending_second_award(self):
        auction = self.db.get(self.auction_id)

        pending_award = {
            'id': uuid4().hex,
            "bid_id": auction['bids'][1]['id'],
            "status": "pending",
            "complaintPeriod": {
                "startDate": get_now().isoformat(),
            }
        }
        unsuccessful_award = deepcopy(pending_award)
        unsuccessful_award['complaintPeriod']['endDate'] = get_now().isoformat()
        unsuccessful_award['id'] = uuid4().hex
        unsuccessful_award['status'] = 'unsuccessful'
        cancelled_award = deepcopy(unsuccessful_award)
        cancelled_award['id'] = uuid4().hex
        cancelled_award['status'] = 'cancelled'

        pending_award['bid_id'] = auction['bids'][0]['id']

        auction['awards'] = [cancelled_award, unsuccessful_award, pending_award]

        auction.update(auction)
        self.db.save(auction)
        migrate_data(self.app.app.registry, 1)
        auction = self.app.get('/auctions/{}'.format(self.auction_id)).json['data']

        self.assertEqual(len(auction['awards']), 3)
        self.assertIn('verificationPeriod', auction['awards'][0])
        self.assertEqual(auction['awards'][0]['status'], 'cancelled')
        self.assertIn('verificationPeriod', auction['awards'][1])
        self.assertEqual(auction['awards'][1]['status'], 'unsuccessful')
        self.assertEqual(auction['awards'][2]['status'], 'pending.payment')
        self.assertIn('verificationPeriod', auction['awards'][2])
        self.assertIn('paymentPeriod', auction['awards'][2])

        response = self.app.get('/auctions/{}'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data']['status'], u'active.qualification')

        response = self.app.get('/auctions/{}/awards'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(len(response.json['data']), 3)
        self.assertEqual(response.json['data'][0]['status'], u'cancelled')
        self.assertEqual(response.json['data'][1]['status'], u'unsuccessful')
        self.assertEqual(response.json['data'][2]['status'], u'pending.payment')

    def test_migrate_cancelled_second_award(self):
        auction = self.db.get(self.auction_id)

        pending_award = {
            'id': uuid4().hex,
            "bid_id": auction['bids'][1]['id'],
            "status": "pending",
            "complaintPeriod": {
                "startDate": get_now().isoformat(),
            }
        }
        unsuccessful_award = deepcopy(pending_award)
        unsuccessful_award['complaintPeriod']['endDate'] = get_now().isoformat()
        unsuccessful_award['id'] = uuid4().hex
        unsuccessful_award['status'] = 'unsuccessful'
        cancelled_award = deepcopy(unsuccessful_award)
        cancelled_award['id'] = uuid4().hex
        cancelled_award['status'] = 'cancelled'

        cancelled_award2 = deepcopy(cancelled_award)
        cancelled_award2['bid_id'] = pending_award['bid_id'] = auction['bids'][0]['id']

        auction['awards'] = [cancelled_award, unsuccessful_award, cancelled_award2, pending_award]

        auction.update(auction)
        self.db.save(auction)
        migrate_data(self.app.app.registry, 1)
        auction = self.app.get('/auctions/{}'.format(self.auction_id)).json['data']

        self.assertEqual(len(auction['awards']), 4)
        self.assertIn('verificationPeriod', auction['awards'][0])
        self.assertEqual(auction['awards'][0]['status'], 'cancelled')
        self.assertIn('verificationPeriod', auction['awards'][1])
        self.assertEqual(auction['awards'][1]['status'], 'unsuccessful')
        self.assertIn('verificationPeriod', auction['awards'][2])
        self.assertEqual(auction['awards'][2]['status'], 'cancelled')
        self.assertEqual(auction['awards'][3]['status'], 'pending.payment')
        self.assertIn('verificationPeriod', auction['awards'][3])
        self.assertIn('paymentPeriod', auction['awards'][3])

        response = self.app.patch_json('/auctions/{}/awards/{}'.format(self.auction_id, pending_award['id']), {"data": {"status": "active"}})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data']['status'], u'active')

        response = self.app.get('/auctions/{}'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data']['status'], u'active.awarded')

        response = self.app.patch_json('/auctions/{}/awards/{}'.format(self.auction_id, pending_award['id']), {"data": {"status": "unsuccessful"}})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data']['status'], u'unsuccessful')

        response = self.app.get('/auctions/{}'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(len(response.json['data']['awards']), 4)
        self.assertEqual(response.json['data']['status'], u'unsuccessful')

        response = self.app.get('/auctions/{}/awards'.format(self.auction_id))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(len(response.json['data']), 4)
        self.assertEqual(response.json['data'][0]['status'], u'cancelled')
        self.assertEqual(response.json['data'][1]['status'], u'unsuccessful')
        self.assertEqual(response.json['data'][2]['status'], u'cancelled')
        self.assertEqual(response.json['data'][3]['status'], u'unsuccessful')


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(MigrateTest))
    suite.addTest(unittest.makeSuite(MigrateTestFrom1To2))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
