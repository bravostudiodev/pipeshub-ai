import 'reflect-metadata'
import { expect } from 'chai'
import sinon from 'sinon'
import { imageAttachmentMembership } from '../../../../src/modules/enterprise_search/controller/image-attachment-membership.controller'
import { ChatSession } from '../../../../src/modules/enterprise_search/schema/chat.session.schema'
import { ChatSessionMessage } from '../../../../src/modules/enterprise_search/schema/chat.session.message.schema'

describe('image attachment membership', () => {
  const orgId = '111111111111111111111111'
  const userId = '222222222222222222222222'
  const conversationId = '333333333333333333333333'
  const req = () => ({ tokenPayload: { orgId, userId }, body: { conversationId, virtualRecordId: 'image' } }) as any
  const response = () => ({ json: sinon.stub(), status: sinon.stub().returnsThis() }) as any
  afterEach(() => sinon.restore())

  it('binds the conversation to the token owner and checks persisted user messages', async () => {
    const sessions = sinon.stub(ChatSession, 'exists').resolves({ _id: conversationId } as any)
    const messages = sinon.stub(ChatSessionMessage, 'exists').resolves({ _id: conversationId } as any)
    const res = response()
    await imageAttachmentMembership(req(), res, sinon.stub())
    expect(sessions.firstCall.args[0]).to.deep.equal({ _id: conversationId, orgId, userId, isDeleted: { $ne: true } })
    expect(messages.firstCall.args[0]).to.deep.equal({ sessionId: conversationId, messageType: 'user_query', attachments: { $elemMatch: { virtualRecordId: 'image', mimeType: { $in: ['image/png', 'image/jpeg', 'image/jpg'] } } } })
    expect(res.json.firstCall.args[0]).to.deep.equal({ allowed: true })
  })

  it('denies another user conversation without looking up messages', async () => {
    sinon.stub(ChatSession, 'exists').resolves(null)
    const messages = sinon.stub(ChatSessionMessage, 'exists')
    const res = response()
    await imageAttachmentMembership(req(), res, sinon.stub())
    expect(res.json.firstCall.args[0]).to.deep.equal({ allowed: false })
    expect(messages.called).to.equal(false)
  })

  it('does not accept identity supplied in the body', async () => {
    const sessions = sinon.stub(ChatSession, 'exists')
    const res = response()
    const request = req()
    request.tokenPayload = {}
    request.body.userId = userId
    request.body.orgId = orgId
    await imageAttachmentMembership(request, res, sinon.stub())
    expect(res.status.firstCall.args[0]).to.equal(400)
    expect(sessions.called).to.equal(false)
  })
})
