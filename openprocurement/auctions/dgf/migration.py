# -*- coding: utf-8 -*-
import logging
from openprocurement.api.models import get_now
from openprocurement.api.utils import calculate_business_date
from barbecue import chef
from uuid import uuid4

from openprocurement.auctions.dgf.models import AWARD_PAYMENT_TIME, CONTRACT_SIGNING_TIME

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


def from0to1(registry):
    results = registry.db.iterview('auctions/all', 2 ** 10, include_docs=True)
    docs = []
    for i in results:
        doc = i.doc
        if doc['procurementMethodType'] not in ['dgfOtherAssets', 'dgfFinancialAssets'] or 'awards' not in doc:
            continue

        changed = False
        now = get_now()
        awards = doc["awards"]

        for a in awards:
            changed = True
            if a['status'] == 'pending':
                a['status'] = 'pending.payment'
                a['verificationPeriod'] = {
                    'startDate': a['complaintPeriod']['startDate'],
                    'endDate': now.isoformat()
                }
                a['paymentPeriod'] = {'startDate': now.isoformat()}
                a['paymentPeriod']['endDate'] = calculate_business_date(now, AWARD_PAYMENT_TIME, doc, True).isoformat()
            elif a['status'] in ['cancelled', 'unsuccessful']:
                a['verificationPeriod'] = a['complaintPeriod']
            elif a['status'] == 'active':
                a['verificationPeriod'] = {'startDate': a['complaintPeriod']['startDate']}
                a['paymentPeriod'] = {'endDate': a['complaintPeriod']['endDate']}
                a['paymentPeriod']['startDate'] = a['verificationPeriod']['endDate'] = a['verificationPeriod']['startDate']
                a['signingPeriod'] = {'startDate': now.isoformat()}
                a['signingPeriod']['endDate'] = calculate_business_date(now, CONTRACT_SIGNING_TIME, doc, True).isoformat()

        unique_awards = len(set([a['bid_id'] for a in awards]))
        if unique_awards == 1:
            bid = chef(doc['bids'], doc.get('features'), [], True)[1]
            award = {
                'id': uuid4().hex,
                'bid_id': bid['id'],
                'status': 'pending.waiting',
                'date': now.isoformat(),
                'value': bid['value'],
                'suppliers': bid['tenderers'],
                'complaintPeriod': {
                    'startDate': now.isoformat()
                }
            }
            awards.append(award)
            changed = True

        if changed:
            doc['dateModified'] = now.isoformat()
            docs.append(doc)
        if len(docs) >= 2 ** 7:
            registry.db.update(docs)
            docs = []
    if docs:
        registry.db.update(docs)
