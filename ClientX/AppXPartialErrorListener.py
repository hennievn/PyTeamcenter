import clr


assy = clr.AddReference("TcSoaClient")  # type: ignore
import Teamcenter.Soa.Client.Model as TcSoaClientModel  # type: ignore

# Implementation of the PartialErrorListener. Print out any partial errors returned.


class AppXPartialErrorListener(TcSoaClientModel.PartialErrorListener):
    __namespace__ = "PyTC_AppXPartialErrorListener"

    def HandlePartialError(self, stacks: list[TcSoaClientModel.ErrorStack]) -> None:
        if not stacks:
            return

        print(
            f"\n*****Partial Errors caught in {self.__class__.__module__}.{self.__class__.__name__}.HandlePartialError."
        )

        for stk in stacks:
            errors = stk.ErrorValues
            error_source_info = "Partial Error"

            # The different service implementation may optionally associate
            # an ModelObject, client ID, or nothing, with each partial error
            if stk.HasAssociatedObject():
                error_source_info += f" for object {stk.AssociatedObject.Uid}"
            elif stk.HasClientId():
                error_source_info += f" for client id {stk.ClientId}"
            elif stk.HasClientIndex():
                error_source_info += f" for client index {stk.ClientIndex}"
            print(error_source_info)

            # Each Partial Error will have one or more contributing error messages
            for er in errors:
                print(f"    Code: {er.Code}\tLevel: {er.Level}\tMessage: {er.Message}")
