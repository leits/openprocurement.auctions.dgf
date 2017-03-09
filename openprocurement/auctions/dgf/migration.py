# -*- coding: utf-8 -*-
import logging
from iso8601 import parse_date
from openprocurement.api.models import get_now, TZ
from openprocurement.api.utils import calculate_business_date
from barbecue import chef
from uuid import uuid4

from openprocurement.auctions.dgf.models import VERIFY_AUCTION_PROTOCOL_TIME, AWARD_PAYMENT_TIME, CONTRACT_SIGNING_TIME
from openprocurement.auctions.dgf.utils import invalidate_bids_under_threshold

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
SCHEMA_DOC = 'openprocurement_auctions_dgf_schema'


def get_db_schema_version(db):
    schema_doc = db.get(SCHEMA_DOC, {"_id": SCHEMA_DOC})
    return schema_doc.get("version", SCHEMA_VERSION - 1)


def set_db_schema_version(db, version):
    schema_doc = db.get(SCHEMA_DOC, {"_id": SCHEMA_DOC})
    schema_doc["version"] = version
    db.save(schema_doc)


def migrate_data(registry, destination=None):
    if registry.settings.get('plugins') and 'auctions.dgf' not in registry.settings['plugins'].split(','):
        return
    cur_version = get_db_schema_version(registry.db)
    if cur_version == SCHEMA_VERSION:
        return cur_version
    for step in xrange(cur_version, destination or SCHEMA_VERSION):
        LOGGER.info("Migrate openprocurement auction schema from {} to {}".format(step, step + 1), extra={'MESSAGE_ID': 'migrate_data'})
        migration_func = globals().get('from{}to{}'.format(step, step + 1))
        if migration_func:
            migration_func(registry)
        set_db_schema_version(registry.db, step + 1)


def disqulify_last_award(auction):
    now = get_now().isoformat()
    excessive_award = [a for a in auction["awards"] if a['status'] in ['active', 'pending']][0]
    if auction['status'] == 'active.awarded':
        for i in auction.contracts:
            if i.awardID == excessive_award.id:
                i.status = 'cancelled'
    excessive_award['status'] = 'unsuccessful'
    excessive_award['complaintPeriod']['endDate'] = now
    auction['awardPeriod']['endDate'] = now
    auction['status'] = 'unsuccessful'


def from0to1(registry):
    results = registry.db.iterview('auctions/all', 2 ** 10, include_docs=True)
    docs = []
    for i in results:
        auction = i.doc
        if auction['procurementMethodType'] not in ['dgfOtherAssets', 'dgfFinancialAssets'] or auction['status'] not in ['active.qualification', 'active.awarded'] or 'awards' not in auction:
            continue

        changed = True
        now = get_now().isoformat()
        awards = auction["awards"]
        unique_awards = len(set([a['bid_id'] for a in awards]))

        if unique_awards > 2:
            disqulify_last_award(auction)

        else:
            invalidate_bids_under_threshold(auction)
            if all(bid['status'] == 'invalid' for bid in auction['bids']):
                disqulify_last_award(auction)
            else:
                for award in awards:

                    if award['status'] in ['active', 'pending'] and all(bid['status'] == 'invalid' for bid in auction['bids'] if bid['id'] == award['bid_id']):
                        award['status'] == 'unsuccessful'
                        award['complaintPeriod']['endDate'] = now
                        continue

                    award_create_date = award['date']

                    award['verificationPeriod'] = {'startDate': award_create_date}
                    award['verificationPeriod']['endDate'] = calculate_business_date(parse_date(award_create_date, TZ), VERIFY_AUCTION_PROTOCOL_TIME, auction, True).isoformat()
                    award['paymentPeriod'] = {'startDate': award_create_date}
                    award['paymentPeriod']['endDate'] = calculate_business_date(parse_date(award_create_date, TZ), AWARD_PAYMENT_TIME, auction, True).isoformat()
                    award['signingPeriod'] = {'startDate': award_create_date}
                    award['signingPeriod']['endDate'] = calculate_business_date(parse_date(award_create_date, TZ), CONTRACT_SIGNING_TIME, auction, True).isoformat()

                    if award['status'] == 'pending':
                        award['status'] = 'pending.verification'
                        award['complaintPeriod']['endDate'] = award['signingPeriod']['endDate']

                    elif award['status'] in ['cancelled', 'unsuccessful']:
                        award['verificationPeriod']['endDate'] = award['paymentPeriod']['endDate'] = award['signingPeriod']['endDate'] = award['complaintPeriod']['endDate']

                    elif award['status'] == 'active':
                        award['verificationPeriod']['endDate'] = award['paymentPeriod']['endDate'] = award['signingPeriod']['endDate']

                if unique_awards == 1:
                    bid = chef(auction['bids'], auction.get('features'), [], True)[1]

                    award = {
                        'id': uuid4().hex,
                        'bid_id': bid['id'],
                        'status': 'pending.waiting',
                        'date': awards[0]['date'],
                        'value': bid['value'],
                        'suppliers': bid['tenderers'],
                        'complaintPeriod': {
                            'startDate': awards[0]['date']
                        }
                    }

                    if bid['status'] == 'invalid':
                        award['status'] = 'unsuccessful'
                        award['complaintPeriod']['endDate'] = now
                    awards.append(award)

        if changed:
            auction['dateModified'] = now
            docs.append(auction)
        if len(docs) >= 2 ** 7:
            registry.db.update(docs)
            docs = []
    if docs:
        registry.db.update(docs)
