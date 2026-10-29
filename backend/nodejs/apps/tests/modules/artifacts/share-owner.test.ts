import { expect } from 'chai';
import sinon from 'sinon';
import { Users } from '../../../src/modules/user_management/schema/users.schema';
import { isShareOwnerActive } from '../../../src/modules/artifacts/services/share-owner';

describe('share owner status', () => {
  afterEach(() => sinon.restore());
  const owner = '507f1f77bcf86cd799439011';
  const org = '507f1f77bcf86cd799439012';

  it('checks a current, active human in the recorded organisation', async () => {
    const find = sinon.stub(Users, 'findOne').returns({ select: () => ({ lean: () => ({ exec: async () => ({ _id: owner }) }) }) } as never);
    expect(await isShareOwnerActive(owner, org)).to.equal(true);
    const filter = find.firstCall.args[0] as Record<string, unknown>;
    expect(filter).to.deep.equal({ _id: owner, orgId: org, isDeleted: { $ne: true }, isDisabled: { $ne: true }, kind: { $ne: 'service' } });
  });

  it('rejects malformed identities and missing accounts', async () => {
    const find = sinon.stub(Users, 'findOne').returns({ select: () => ({ lean: () => ({ exec: async () => null }) }) } as never);
    expect(await isShareOwnerActive('bad', org)).to.equal(false);
    expect(find.called).to.equal(false);
    expect(await isShareOwnerActive(owner, org)).to.equal(false);
  });

  it('propagates database failures', async () => {
    sinon.stub(Users, 'findOne').returns({ select: () => ({ lean: () => ({ exec: async () => { throw new Error('offline'); } }) }) } as never);
    try { await isShareOwnerActive(owner, org); expect.fail('expected failure'); } catch (error) {
      expect((error as Error).message).to.equal('offline');
    }
  });
});
